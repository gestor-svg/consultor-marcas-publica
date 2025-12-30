import os
import requests
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
import google.generativeai as genai
import json
from functools import lru_cache
import time
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURACIÓN ---
API_KEY_GEMINI = os.environ.get("API_KEY_GEMINI")
GOOGLE_APPS_SCRIPT_URL = os.environ.get("GOOGLE_APPS_SCRIPT_URL")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")
EMAIL_DESTINO = "gestor@marcasegura.com.mx"

# DEBUG MODE - Cambiar a False en producción
DEBUG_IMPI = True

# Diccionario completo de Clases de Niza (Clasificación Internacional de Marcas)
CLASES_NIZA = {
    "1": "Productos químicos",
    "2": "Pinturas y barnices",
    "3": "Cosméticos y productos de limpieza",
    "4": "Lubricantes y combustibles",
    "5": "Productos farmacéuticos",
    "6": "Metales comunes y sus aleaciones",
    "7": "Máquinas y máquinas herramientas",
    "8": "Herramientas e instrumentos de mano",
    "9": "Aparatos e instrumentos científicos y electrónicos",
    "10": "Aparatos e instrumentos médicos",
    "11": "Aparatos de iluminación, calefacción y cocción",
    "12": "Vehículos y medios de transporte",
    "13": "Armas de fuego y pirotecnia",
    "14": "Joyería y relojería",
    "15": "Instrumentos musicales",
    "16": "Papel, cartón y artículos de oficina",
    "17": "Caucho, plásticos y materiales aislantes",
    "18": "Cuero, equipaje y artículos de viaje",
    "19": "Materiales de construcción no metálicos",
    "20": "Muebles y artículos de madera",
    "21": "Utensilios de cocina y recipientes",
    "22": "Cuerdas, lonas y materiales textiles",
    "23": "Hilos para uso textil",
    "24": "Tejidos y cubiertas textiles",
    "25": "Prendas de vestir, calzado y sombreros",
    "26": "Artículos de mercería y pasamanería",
    "27": "Alfombras y revestimientos de suelos",
    "28": "Juegos, juguetes y artículos deportivos",
    "29": "Carne, pescado, frutas y verduras procesadas",
    "30": "Café, té, cacao, pan y pastelería",
    "31": "Productos agrícolas y forestales",
    "32": "Cervezas, bebidas sin alcohol y aguas",
    "33": "Bebidas alcohólicas (excepto cervezas)",
    "34": "Tabaco y artículos para fumadores",
    "35": "Publicidad y gestión de negocios",
    "36": "Servicios financieros y de seguros",
    "37": "Servicios de construcción y reparación",
    "38": "Servicios de telecomunicaciones",
    "39": "Servicios de transporte y almacenamiento",
    "40": "Tratamiento de materiales",
    "41": "Educación, formación y entretenimiento",
    "42": "Servicios científicos y tecnológicos",
    "43": "Servicios de restauración y hospedaje",
    "44": "Servicios médicos y de belleza",
    "45": "Servicios jurídicos y de seguridad",
}

def obtener_nombre_clase(numero_clase):
    """Obtiene el nombre descriptivo de una clase de Niza"""
    return CLASES_NIZA.get(str(numero_clase), f"Clase {numero_clase}")

if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    print("✓ Gemini configurado")
else:
    print("⚠ API_KEY_GEMINI no encontrada")

def normalizar_marca(marca):
    """Normaliza el nombre de la marca para búsqueda"""
    marca = marca.strip()
    # No convertir a mayúsculas - el IMPI maneja ambos
    marca = re.sub(r'\s+', ' ', marca)
    return marca

@lru_cache(maxsize=100)
def clasificar_con_gemini(descripcion, tipo_negocio):
    """Usa Gemini para determinar la clase de Niza"""
    if not API_KEY_GEMINI:
        return {
            "clase_principal": "35",
            "clase_nombre": "Servicios comerciales",
            "clases_adicionales": [],
            "nota": "IA no disponible"
        }
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""Clasifica según Niza: {descripcion} ({tipo_negocio})

Responde SOLO en este formato exacto (una línea):
CLASE|NOMBRE|NOTA

Ejemplo: 43|Restaurantes y cafeterías|Servicios de alimentación

Claves: Bebidas=32, Alimentos=29-30, Restaurantes=43, Ropa=25, Software=9, Comercial=35, IT=42
Productos=1-34, Servicios=35-45"""

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=150,
            )
        )
        
        text = response.text.strip()
        print(f"[GEMINI DEBUG] Respuesta: {text}")
        
        if '|' in text:
            partes = text.split('|')
            if len(partes) >= 3:
                clase = partes[0].strip()
                nombre = partes[1].strip()
                nota = partes[2].strip()
                
                match = re.search(r'\d+', clase)
                clase_num = match.group() if match else clase
                
                print(f"[GEMINI] ✓ Clase: {clase_num} - {nombre}")
                return {
                    "clase_principal": clase_num,
                    "clase_nombre": nombre,
                    "clases_adicionales": [],
                    "nota": nota
                }
        
        numeros = re.findall(r'\b\d{1,2}\b', text)
        if numeros:
            clase_num = numeros[0]
            clase_nombre = obtener_nombre_clase(clase_num)
            print(f"[GEMINI] ⚠ Clase extraída: {clase_num} - {clase_nombre}")
            return {
                "clase_principal": clase_num,
                "clase_nombre": clase_nombre,
                "clases_adicionales": [],
                "nota": text[:100]
            }
        
        raise ValueError("No se pudo extraer clase")
        
    except Exception as e:
        print(f"[ERROR GEMINI] {e}")
        # Fallback inteligente usando el diccionario de clases
        if tipo_negocio.lower() == 'producto':
            if any(kw in descripcion.lower() for kw in ['bebida', 'refresco', 'agua', 'jugo']):
                return {"clase_principal": "32", "clase_nombre": obtener_nombre_clase("32"), "clases_adicionales": [], "nota": "Clasificación automática"}
            elif any(kw in descripcion.lower() for kw in ['comida', 'alimento', 'snack']):
                return {"clase_principal": "29", "clase_nombre": obtener_nombre_clase("29"), "clases_adicionales": [], "nota": "Clasificación automática"}
            elif any(kw in descripcion.lower() for kw in ['ropa', 'vestido', 'calzado']):
                return {"clase_principal": "25", "clase_nombre": obtener_nombre_clase("25"), "clases_adicionales": [], "nota": "Clasificación automática"}
            elif any(kw in descripcion.lower() for kw in ['software', 'app', 'programa', 'tecnolog']):
                return {"clase_principal": "9", "clase_nombre": obtener_nombre_clase("9"), "clases_adicionales": [], "nota": "Clasificación automática"}
            return {"clase_principal": "1", "clase_nombre": obtener_nombre_clase("1"), "clases_adicionales": [], "nota": "Clasificación por defecto"}
        else:
            if any(kw in descripcion.lower() for kw in ['restaurante', 'cafetería', 'bar', 'comida', 'café']):
                return {"clase_principal": "43", "clase_nombre": obtener_nombre_clase("43"), "clases_adicionales": [], "nota": "Clasificación automática"}
            elif any(kw in descripcion.lower() for kw in ['software', 'desarrollo', 'tecnolog', 'it', 'sistemas']):
                return {"clase_principal": "42", "clase_nombre": obtener_nombre_clase("42"), "clases_adicionales": [], "nota": "Clasificación automática"}
            return {"clase_principal": "35", "clase_nombre": obtener_nombre_clase("35"), "clases_adicionales": [], "nota": "Clasificación por defecto"}


def buscar_impi_simple(marca):
    """
    Búsqueda en IMPI usando JSF/PrimeFaces AJAX
    Basada en el análisis del formulario real de MARCANET
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-MX,es;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    })
    
    marca_buscar = normalizar_marca(marca)
    
    print(f"\n{'='*60}")
    print(f"[IMPI] Buscando marca: '{marca_buscar}'")
    print(f"{'='*60}")
    
    try:
        # ============================================
        # PASO 1: Obtener página inicial y ViewState
        # ============================================
        print(f"[PASO 1] Obteniendo página inicial y ViewState...")
        
        url_base = "https://acervomarcas.impi.gob.mx:8181/marcanet/"
        
        response_inicial = session.get(url_base, timeout=30, verify=True)
        
        if response_inicial.status_code != 200:
            print(f"[IMPI] ✗ Error al cargar página: {response_inicial.status_code}")
            return "ERROR_CONEXION"
        
        print(f"  Status: {response_inicial.status_code}")
        print(f"  Cookies: {dict(session.cookies)}")
        
        # Extraer ViewState (token JSF obligatorio)
        soup_inicial = BeautifulSoup(response_inicial.text, 'html.parser')
        viewstate_input = soup_inicial.find('input', {'name': 'javax.faces.ViewState'})
        
        if not viewstate_input:
            print(f"[IMPI] ✗ No se encontró ViewState")
            return "ERROR_CONEXION"
        
        viewstate = viewstate_input.get('value', '')
        print(f"  ViewState: {viewstate[:50]}...")
        
        if DEBUG_IMPI:
            with open('/tmp/impi_01_inicial.html', 'w', encoding='utf-8') as f:
                f.write(response_inicial.text)
        
        # ============================================
        # PASO 2: Enviar búsqueda AJAX (PrimeFaces)
        # ============================================
        print(f"\n[PASO 2] Enviando búsqueda AJAX...")
        
        url_busqueda = "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/home.pgi"
        
        # Datos para petición AJAX de PrimeFaces
        data_busqueda = {
            'javax.faces.partial.ajax': 'true',
            'javax.faces.source': 'frmBsqDen:busquedaIdButton',
            'javax.faces.partial.execute': 'frmBsqDen:busquedaIdButton frmBsqDen:denominacionId frmBsqDen:swtExacto',
            'javax.faces.partial.render': 'frmBsqDen',
            'frmBsqDen:busquedaIdButton': 'frmBsqDen:busquedaIdButton',
            'frmBsqDen': 'frmBsqDen',
            'frmBsqDen:denominacionId': marca_buscar,
            'javax.faces.ViewState': viewstate,
        }
        
        headers_ajax = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Faces-Request': 'partial/ajax',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://acervomarcas.impi.gob.mx:8181',
            'Referer': url_base,
        }
        
        print(f"  URL: {url_busqueda}")
        print(f"  Marca: {marca_buscar}")
        
        response_busqueda = session.post(
            url_busqueda,
            data=data_busqueda,
            headers=headers_ajax,
            timeout=30
        )
        
        print(f"  Status: {response_busqueda.status_code}")
        print(f"  Response length: {len(response_busqueda.text)} bytes")
        
        if DEBUG_IMPI:
            with open('/tmp/impi_02_busqueda.xml', 'w', encoding='utf-8') as f:
                f.write(response_busqueda.text)
        
        if response_busqueda.status_code != 200:
            print(f"[IMPI] ✗ Error en búsqueda: {response_busqueda.status_code}")
            return "ERROR_CONEXION"
        
        # ============================================
        # PASO 3: Analizar respuesta AJAX
        # ============================================
        print(f"\n[PASO 3] Analizando respuesta...")
        
        respuesta_texto = response_busqueda.text
        
        # La respuesta AJAX de PrimeFaces viene en formato XML con CDATA
        # Buscar el contenido HTML dentro del CDATA
        
        # Parsear como XML para extraer el HTML
        soup_resp = BeautifulSoup(respuesta_texto, 'html.parser')
        
        # También buscar directamente en el texto
        texto_lower = respuesta_texto.lower()
        
        # ============================================
        # DETECCIÓN DE RESULTADOS
        # ============================================
        
        # Método 1: Buscar "Total de registros"
        match_total = re.search(r'total de registros\s*=\s*(\d+)', texto_lower)
        if match_total:
            total_registros = int(match_total.group(1))
            print(f"  ✓ Total de registros encontrado: {total_registros}")
            
            if total_registros > 0:
                print(f"\n[IMPI] ✗ MARCA ENCONTRADA - {total_registros} registros")
                return "REQUIERE_ANALISIS"
        
        # Método 2: Buscar tabla de resultados con datos
        if 'frmBsqDen:resultadoExpediente_data' in respuesta_texto:
            print(f"  ✓ Tabla de resultados detectada")
            
            # Buscar filas de datos (ui-datatable-even o ui-datatable-odd)
            filas_data = re.findall(r'ui-datatable-(even|odd)', respuesta_texto)
            if filas_data:
                num_filas = len(filas_data)
                print(f"  ✓ Filas de datos encontradas: {num_filas}")
                
                if num_filas > 0:
                    print(f"\n[IMPI] ✗ MARCA ENCONTRADA - {num_filas} filas")
                    return "REQUIERE_ANALISIS"
        
        # Método 3: Buscar indicadores específicos de registros
        indicadores_registro = [
            'registro de marca',
            'nominativa',
            'mixta',
            'innominada',
            'tridimensional'
        ]
        
        indicadores_encontrados = sum(1 for ind in indicadores_registro if ind in texto_lower)
        
        if indicadores_encontrados >= 2:
            print(f"  ✓ Indicadores de registro: {indicadores_encontrados}")
            
            # Verificar que la marca buscada aparece en los resultados
            if marca_buscar.lower() in texto_lower:
                print(f"  ✓ Marca '{marca_buscar}' encontrada en resultados")
                print(f"\n[IMPI] ✗ MARCA ENCONTRADA")
                return "REQUIERE_ANALISIS"
        
        # Método 4: Buscar expedientes (números de 5-6 dígitos en contexto de resultados)
        if 'expediente' in texto_lower:
            expedientes = re.findall(r'>(\d{5,6})</a>', respuesta_texto)
            if expedientes:
                print(f"  ✓ Expedientes encontrados: {expedientes[:5]}...")
                print(f"\n[IMPI] ✗ MARCA ENCONTRADA - {len(expedientes)} expedientes")
                return "REQUIERE_ANALISIS"
        
        # Método 5: Verificar si la tabla está vacía
        # Si hay tabla pero sin filas de datos
        if 'resultadoExpediente' in respuesta_texto:
            if 'ui-datatable-empty-message' in respuesta_texto or 'No se encontraron' in respuesta_texto:
                print(f"  ✓ Tabla vacía - Sin resultados")
                print(f"\n[IMPI] ✓ MARCA POSIBLEMENTE DISPONIBLE")
                return "POSIBLEMENTE_DISPONIBLE"
        
        # Método 6: Si no hay tabla de resultados en absoluto
        if 'resultadoExpediente' not in respuesta_texto and 'pnlResultados' in respuesta_texto:
            # La tabla de resultados existe pero está vacía
            tabla_vacia = '<tr><td></td></tr>' in respuesta_texto or 'pnlResultados"><tbody><tr><td></td></tr>' in respuesta_texto.replace('\n', '').replace(' ', '')
            if tabla_vacia:
                print(f"  ✓ Panel de resultados vacío")
                print(f"\n[IMPI] ✓ MARCA POSIBLEMENTE DISPONIBLE")
                return "POSIBLEMENTE_DISPONIBLE"
        
        # ============================================
        # Si llegamos aquí, no pudimos determinar con certeza
        # ============================================
        print(f"\n[IMPI] ⚠ No se pudo determinar con certeza")
        print(f"  Respuesta contiene 'resultadoExpediente': {'resultadoExpediente' in respuesta_texto}")
        print(f"  Respuesta contiene 'registro de marca': {'registro de marca' in texto_lower}")
        print(f"  Respuesta contiene marca '{marca_buscar}': {marca_buscar.lower() in texto_lower}")
        
        # Por seguridad, si no podemos confirmar que está vacío, asumimos que requiere análisis
        if len(respuesta_texto) > 5000:  # Respuesta grande probablemente tiene resultados
            print(f"  Respuesta grande ({len(respuesta_texto)} bytes) - probablemente tiene resultados")
            return "REQUIERE_ANALISIS"
        
        return "REQUIERE_ANALISIS"  # Conservador por defecto
        
    except requests.exceptions.SSLError as e:
        print(f"[IMPI] Error SSL: {e}")
        return "ERROR_CONEXION"
    except requests.exceptions.Timeout as e:
        print(f"[IMPI] Timeout: {e}")
        return "ERROR_CONEXION"
    except requests.exceptions.ConnectionError as e:
        print(f"[IMPI] Error de conexión: {e}")
        return "ERROR_CONEXION"
    except Exception as e:
        print(f"[IMPI] Error general: {e}")
        import traceback
        traceback.print_exc()
        return "ERROR_CONEXION"


def guardar_lead_google_sheets(datos_lead):
    """Guarda el lead en Google Sheets"""
    if not GOOGLE_APPS_SCRIPT_URL:
        print("⚠ Google Apps Script URL no configurada")
        return False
    
    try:
        response = requests.post(
            GOOGLE_APPS_SCRIPT_URL,
            json=datos_lead,
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"[SHEETS] ✓ Lead guardado: {datos_lead['nombre']}")
            return True
        else:
            print(f"[SHEETS] ✗ Error {response.status_code}")
            return False
        
    except Exception as e:
        print(f"[SHEETS] ✗ Error: {e}")
        return False


def enviar_email_lead(datos_lead):
    """Envía email con Gmail SMTP"""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("⚠ Gmail SMTP no configurado")
        return False
    
    try:
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                <h1 style="color: white; margin: 0;">🎯 Nuevo Lead Capturado</h1>
            </div>
            
            <div style="padding: 30px; background: #f7fafc;">
                <h2 style="color: #2d3748;">Datos del Cliente</h2>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><strong>Nombre:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{datos_lead['nombre']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><strong>Email:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">
                            <a href="mailto:{datos_lead['email']}">{datos_lead['email']}</a>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><strong>Teléfono:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">
                            <a href="tel:{datos_lead['telefono']}">{datos_lead['telefono']}</a>
                        </td>
                    </tr>
                </table>
                
                <h2 style="color: #2d3748; margin-top: 30px;">Consulta Realizada</h2>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><strong>Marca:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{datos_lead['marca']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><strong>Tipo:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{datos_lead['tipo_negocio']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><strong>Status IMPI:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">
                            <span style="background: #feebc8; padding: 5px 10px; border-radius: 5px; color: #744210;">
                                {datos_lead['status_impi']}
                            </span>
                        </td>
                    </tr>
                </table>
                
                <div style="background: #fff; padding: 20px; margin-top: 20px; border-radius: 10px; border-left: 4px solid #667eea;">
                    <p style="margin: 0; color: #4a5568;"><strong>Mensaje mostrado:</strong></p>
                    <p style="margin: 10px 0 0 0; color: #2d3748;">{datos_lead['resultado']}</p>
                </div>
                
                <p style="color: #718096; font-size: 12px; margin-top: 30px; text-align: center;">
                    📅 {datos_lead['fecha']} - {datos_lead['hora']}<br>
                    Consultor de Marcas | MarcaSegura
                </p>
            </div>
        </body>
        </html>
        """
        
        mensaje = MIMEMultipart('alternative')
        mensaje['Subject'] = f"🎯 Nuevo Lead - {datos_lead['nombre']} | Marca: {datos_lead['marca']}"
        mensaje['From'] = GMAIL_USER
        mensaje['To'] = EMAIL_DESTINO
        
        parte_html = MIMEText(html_content, 'html', 'utf-8')
        mensaje.attach(parte_html)
        
        servidor = smtplib.SMTP('smtp.gmail.com', 587)
        servidor.starttls()
        servidor.login(GMAIL_USER, GMAIL_PASSWORD)
        servidor.send_message(mensaje)
        servidor.quit()
        
        print(f"[EMAIL] ✓ Email enviado a {EMAIL_DESTINO}")
        return True
        
    except Exception as e:
        print(f"[EMAIL] ✗ Error: {e}")
        return False


# ============================================
# RUTAS FLASK
# ============================================

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/analizar', methods=['POST'])
def analizar():
    """Endpoint principal de análisis"""
    data = request.json
    marca = data.get('marca', '').strip()
    descripcion = data.get('descripcion', '').strip()
    tipo_negocio = data.get('tipo', 'servicio').lower()
    
    if not marca or not descripcion:
        return jsonify({"error": "Marca y descripción son obligatorias"}), 400
    
    print(f"\n{'='*70}")
    print(f"ANÁLISIS DE MARCA - Versión Pública")
    print(f"Marca: {marca}")
    print(f"Descripción: {descripcion[:50]}...")
    print(f"Tipo: {tipo_negocio}")
    print(f"{'='*70}")
    
    # 1. Clasificar con Gemini
    clasificacion = clasificar_con_gemini(descripcion, tipo_negocio)
    
    # 2. Búsqueda en IMPI
    status_impi = buscar_impi_simple(marca)
    
    # 3. Preparar respuesta según resultado
    if status_impi == "POSIBLEMENTE_DISPONIBLE":
        mensaje = f"¡Buenas noticias! No encontramos coincidencias exactas de '{marca}' en nuestra búsqueda preliminar."
        icono = "✓"
        color = "success"
        cta = "Sin embargo, esto NO garantiza disponibilidad total. Se requiere un análisis fonético y fonográfico completo por un especialista para verificar todas las variantes posibles. Déjanos tus datos para realizar el estudio técnico profesional."
        
    elif status_impi == "REQUIERE_ANALISIS":
        mensaje = f"Encontramos registros relacionados con '{marca}' en la base de datos del IMPI."
        icono = "⚠️"
        color = "warning"
        cta = "Tu marca o una similar ya podría estar registrada. Agenda una consulta con nuestro ejecutivo para analizar alternativas disponibles y encontrar el nombre perfecto para tu negocio. Déjanos tus datos y te contactaremos dentro de 24 horas."
    
    elif status_impi == "ERROR_CONEXION":
        mensaje = f"No pudimos conectar con el servidor del IMPI en este momento."
        icono = "🔄"
        color = "info"
        cta = "Por favor intenta nuevamente en unos minutos o déjanos tus datos para realizar la búsqueda manualmente y contactarte con los resultados."
        
    else:
        mensaje = f"No pudimos completar la búsqueda de '{marca}'."
        icono = "🔍"
        color = "info"
        cta = "Déjanos tus datos para realizar la búsqueda manualmente y contactarte con los resultados en menos de 24 horas."
    
    resultado = {
        "mensaje": mensaje,
        "icono": icono,
        "color": color,
        "clase_sugerida": f"Clase {clasificacion['clase_principal']}: {clasificacion['clase_nombre']}",
        "clases_adicionales": clasificacion.get('clases_adicionales', []),
        "nota_tecnica": clasificacion.get('nota', ''),
        "mostrar_formulario": True,
        "cta": cta,
        "status_impi": status_impi,
        "tipo_negocio": tipo_negocio
    }
    
    print(f"\n[RESULTADO FINAL] Status: {status_impi}")
    print(f"[RESULTADO FINAL] Clase: {clasificacion['clase_principal']}")
    print(f"{'='*70}\n")
    
    return jsonify(resultado)


@app.route('/capturar-lead', methods=['POST'])
def capturar_lead():
    """Captura el lead y envía notificaciones"""
    data = request.json
    
    datos_lead = {
        'fecha': datetime.now().strftime('%Y-%m-%d'),
        'hora': datetime.now().strftime('%H:%M:%S'),
        'nombre': data.get('nombre', ''),
        'email': data.get('email', ''),
        'telefono': data.get('telefono', ''),
        'marca': data.get('marca', ''),
        'tipo_negocio': data.get('tipo_negocio', ''),
        'resultado': data.get('resultado', ''),
        'status_impi': data.get('status_impi', '')
    }
    
    if not all([datos_lead['nombre'], datos_lead['email'], datos_lead['telefono']]):
        return jsonify({"error": "Todos los campos son obligatorios"}), 400
    
    print(f"\n[LEAD CAPTURADO] {datos_lead['nombre']} - {datos_lead['marca']}")
    
    # Guardar en Google Sheets y enviar email
    guardar_lead_google_sheets(datos_lead)
    enviar_email_lead(datos_lead)
    
    # Generar link de calendario
    from urllib.parse import quote
    titulo = f"Consulta de Marca - {datos_lead['nombre']}"
    desc = f"Análisis para la marca: {datos_lead['marca']}"
    calendar_link = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={quote(titulo)}&details={quote(desc)}"
    
    return jsonify({
        "success": True,
        "mensaje": "¡Gracias! Hemos recibido tu información.",
        "calendar_link": calendar_link
    })


# ============================================
# ENDPOINTS DE DEBUG
# ============================================

@app.route('/debug/test/<marca>')
def debug_test(marca):
    """Endpoint para probar búsqueda directamente"""
    resultado = buscar_impi_simple(marca)
    
    # Intentar leer archivos de debug
    debug_files = {}
    for filename in ['impi_01_inicial.html', 'impi_02_busqueda.xml']:
        try:
            with open(f'/tmp/{filename}', 'r', encoding='utf-8') as f:
                content = f.read()
                debug_files[filename] = {
                    'size': len(content),
                    'preview': content[:500] + '...' if len(content) > 500 else content
                }
        except:
            pass
    
    return jsonify({
        "marca": marca,
        "resultado": resultado,
        "debug_files": debug_files
    })


@app.route('/debug/files')
def debug_files():
    """Lista archivos de debug"""
    import os
    files = []
    try:
        for f in os.listdir('/tmp'):
            if f.startswith('impi_'):
                filepath = f'/tmp/{f}'
                files.append({
                    'name': f,
                    'size': os.path.getsize(filepath),
                    'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
                })
    except:
        pass
    return jsonify({"files": files})


@app.route('/debug/file/<filename>')
def debug_file(filename):
    """Ver contenido de archivo de debug"""
    from flask import Response
    
    if not filename.startswith('impi_'):
        return jsonify({"error": "Archivo no válido"}), 400
    
    try:
        with open(f'/tmp/{filename}', 'r', encoding='utf-8') as f:
            content = f.read()
        
        if filename.endswith('.json'):
            return jsonify(json.loads(content))
        elif filename.endswith('.xml'):
            return Response(content, mimetype='application/xml')
        else:
            return Response(content, mimetype='text/html')
    except FileNotFoundError:
        return jsonify({"error": "Archivo no encontrado"}), 404


@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "version": "publica-2.0-jsf",
        "debug_mode": DEBUG_IMPI,
        "gemini": bool(API_KEY_GEMINI),
        "sheets": bool(GOOGLE_APPS_SCRIPT_URL),
        "email": bool(GMAIL_USER and GMAIL_PASSWORD),
        "timestamp": datetime.now().isoformat()
    })


# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    print(f"\n{'='*70}")
    print(f"🌐 CONSULTOR DE MARCAS - VERSIÓN PÚBLICA v2.0")
    print(f"{'='*70}")
    print(f"Puerto: {port}")
    print(f"Debug IMPI: {'✓ ACTIVADO' if DEBUG_IMPI else '✗ Desactivado'}")
    print(f"Gemini: {'✓' if API_KEY_GEMINI else '✗'}")
    print(f"Google Sheets: {'✓' if GOOGLE_APPS_SCRIPT_URL else '✗'}")
    print(f"Gmail SMTP: {'✓' if (GMAIL_USER and GMAIL_PASSWORD) else '✗'}")
    print(f"{'='*70}")
    print(f"Endpoints:")
    print(f"  GET  /                    - Página principal")
    print(f"  POST /analizar            - Analizar marca")
    print(f"  POST /capturar-lead       - Capturar lead")
    print(f"  GET  /debug/test/<marca>  - Probar búsqueda")
    print(f"  GET  /debug/files         - Listar archivos debug")
    print(f"  GET  /health              - Health check")
    print(f"{'='*70}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
