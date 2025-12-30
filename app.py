import os
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
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
from urllib.parse import quote

import threading

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "marcasegura-secret-key-2025")

# --- CONFIGURACIÓN ---
API_KEY_GEMINI = os.environ.get("API_KEY_GEMINI")
GOOGLE_APPS_SCRIPT_URL = os.environ.get("GOOGLE_APPS_SCRIPT_URL", "https://script.google.com/macros/s/AKfycbxVUnURWycPV5vy7m7ZEWS2vDDzunjYNanO8vOxsuO-QZ2h3nP9GGMBUbE5fR7dUYn_cg/exec")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")
EMAIL_DESTINO = "gestor@marcasegura.com.mx"

# CONFIGURACIÓN DE VENTAS
PRECIO_REPORTE = 950  # MXN
MERCADO_PAGO_LINK = os.environ.get("MERCADO_PAGO_LINK", "https://mpago.li/2xfRia")
WHATSAPP_NUMERO = os.environ.get("WHATSAPP_NUMERO", "523331562224")
CAL_COM_URL = os.environ.get("CAL_COM_URL", "https://cal.com/marcasegura/30min")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://consultor-marcas-publica.onrender.com")

# DEBUG MODE
DEBUG_IMPI = os.environ.get("DEBUG_IMPI", "false").lower() == "true"

if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    print("✓ Gemini configurado")
else:
    print("⚠ API_KEY_GEMINI no encontrada")

# Diccionario completo de Clases de Niza
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


def normalizar_marca(marca):
    """Normaliza el nombre de la marca para búsqueda"""
    marca = marca.strip()
    marca = re.sub(r'\s+', ' ', marca)
    return marca


def generar_mensaje_whatsapp(datos_lead, datos_facturacion=None):
    """Genera el mensaje de WhatsApp con los datos del cliente"""
    mensaje = f"""🎯 *NUEVO CLIENTE - REPORTE PAGADO*

📋 *Datos del Lead:*
• Nombre: {datos_lead.get('nombre', 'N/A')}
• Email: {datos_lead.get('email', 'N/A')}
• Teléfono: {datos_lead.get('telefono', 'N/A')}

🏷️ *Consulta:*
• Marca: {datos_lead.get('marca', 'N/A')}
• Tipo: {datos_lead.get('tipo_negocio', 'N/A')}
• Clase: {datos_lead.get('clase_sugerida', 'N/A')}
• Status IMPI: {datos_lead.get('status_impi', 'N/A')}
"""
    
    if datos_facturacion:
        mensaje += f"""
💳 *Facturación:*
• Requiere Factura: {datos_facturacion.get('requiere_factura', 'No')}"""
        if datos_facturacion.get('requiere_factura') == 'Si':
            mensaje += f"""
• RFC: {datos_facturacion.get('rfc', 'N/A')}
• Razón Social: {datos_facturacion.get('razon_social', 'N/A')}
• Régimen: {datos_facturacion.get('regimen_fiscal', 'N/A')}
• Uso CFDI: {datos_facturacion.get('uso_cfdi', 'N/A')}
• CP: {datos_facturacion.get('codigo_postal', 'N/A')}"""
    
    mensaje += f"""

📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}
💰 Pago: $950 MXN ✅
"""
    
    return mensaje


@lru_cache(maxsize=100)
def clasificar_con_gemini(descripcion, tipo_negocio):
    """Usa Gemini para determinar la clase de Niza"""
    if not API_KEY_GEMINI:
        return {
            "clase_principal": "35",
            "clase_nombre": obtener_nombre_clase("35"),
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
    """Búsqueda en IMPI usando JSF/PrimeFaces AJAX"""
    session_req = requests.Session()
    session_req.headers.update({
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
        # PASO 1: Obtener ViewState
        url_base = "https://acervomarcas.impi.gob.mx:8181/marcanet/"
        response_inicial = session_req.get(url_base, timeout=30, verify=True)
        
        if response_inicial.status_code != 200:
            print(f"[IMPI] ✗ Error: {response_inicial.status_code}")
            return "ERROR_CONEXION"
        
        soup_inicial = BeautifulSoup(response_inicial.text, 'html.parser')
        viewstate_input = soup_inicial.find('input', {'name': 'javax.faces.ViewState'})
        
        if not viewstate_input:
            return "ERROR_CONEXION"
        
        viewstate = viewstate_input.get('value', '')
        
        # PASO 2: Búsqueda AJAX
        url_busqueda = "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/home.pgi"
        
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
        
        response_busqueda = session_req.post(url_busqueda, data=data_busqueda, headers=headers_ajax, timeout=30)
        
        if response_busqueda.status_code != 200:
            return "ERROR_CONEXION"
        
        # PASO 3: Analizar respuesta
        respuesta_texto = response_busqueda.text
        texto_lower = respuesta_texto.lower()
        
        # Detectar resultados
        match_total = re.search(r'total de registros\s*=\s*(\d+)', texto_lower)
        if match_total and int(match_total.group(1)) > 0:
            print(f"[IMPI] ✗ MARCA ENCONTRADA - {match_total.group(1)} registros")
            return "REQUIERE_ANALISIS"
        
        if 'frmBsqDen:resultadoExpediente_data' in respuesta_texto:
            filas = re.findall(r'ui-datatable-(even|odd)', respuesta_texto)
            if filas:
                print(f"[IMPI] ✗ MARCA ENCONTRADA - {len(filas)} filas")
                return "REQUIERE_ANALISIS"
        
        indicadores = ['registro de marca', 'nominativa', 'mixta']
        if sum(1 for i in indicadores if i in texto_lower) >= 2:
            if marca_buscar.lower() in texto_lower:
                print(f"[IMPI] ✗ MARCA ENCONTRADA")
                return "REQUIERE_ANALISIS"
        
        if 'ui-datatable-empty-message' in respuesta_texto:
            print(f"[IMPI] ✓ MARCA POSIBLEMENTE DISPONIBLE")
            return "POSIBLEMENTE_DISPONIBLE"
        
        if len(respuesta_texto) > 5000:
            return "REQUIERE_ANALISIS"
        
        return "REQUIERE_ANALISIS"
        
    except Exception as e:
        print(f"[IMPI] Error: {e}")
        return "ERROR_CONEXION"


def guardar_en_sheets(datos, hoja="leads"):
    """Guarda datos en Google Sheets"""
    if not GOOGLE_APPS_SCRIPT_URL:
        print("⚠ Google Apps Script no configurado")
        return False
    
    try:
        payload = {'hoja': hoja, 'datos': datos}
        response = requests.post(GOOGLE_APPS_SCRIPT_URL, json=payload, timeout=15)
        
        if response.status_code == 200:
            print(f"[SHEETS] ✓ Guardado en '{hoja}'")
            return True
        print(f"[SHEETS] ✗ Error {response.status_code}")
        return False
    except Exception as e:
        print(f"[SHEETS] ✗ Error: {e}")
        return False


def enviar_email_lead(datos_lead):
    """Envía email de notificación (versión ligera)"""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("[EMAIL] ⚠ No configurado")
        return False
    
    try:
        # Usar texto plano en lugar de HTML para reducir memoria
        texto = f"""
NUEVO LEAD - CONSULTOR DE MARCAS

Nombre: {datos_lead.get('nombre', 'N/A')}
Email: {datos_lead.get('email', 'N/A')}
Teléfono: {datos_lead.get('telefono', 'N/A')}

Marca: {datos_lead.get('marca', 'N/A')}
Status: {datos_lead.get('status_impi', 'N/A')}
Clase: {datos_lead.get('clase_sugerida', 'N/A')}

Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """
        
        mensaje = MIMEText(texto, 'plain', 'utf-8')
        mensaje['Subject'] = f"Lead - {datos_lead.get('nombre', 'Cliente')} | {datos_lead.get('marca', 'Marca')}"
        mensaje['From'] = GMAIL_USER
        mensaje['To'] = EMAIL_DESTINO
        
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=10) as servidor:
            servidor.starttls()
            servidor.login(GMAIL_USER, GMAIL_PASSWORD)
            servidor.send_message(mensaje)
        
        print(f"[EMAIL] ✓ Enviado")
        return True
    except Exception as e:
        print(f"[EMAIL] ✗ {e}")
        return False


# ============================================
# RUTAS FLASK
# ============================================

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/analizar', methods=['POST'])
def analizar():
    """Análisis de marca"""
    data = request.json
    marca = data.get('marca', '').strip()
    descripcion = data.get('descripcion', '').strip()
    tipo_negocio = data.get('tipo', 'servicio').lower()
    
    if not marca or not descripcion:
        return jsonify({"error": "Marca y descripción son obligatorias"}), 400
    
    print(f"\n{'='*70}\nANÁLISIS: {marca}\n{'='*70}")
    
    clasificacion = clasificar_con_gemini(descripcion, tipo_negocio)
    status_impi = buscar_impi_simple(marca)
    
    clase_sugerida = f"Clase {clasificacion['clase_principal']}: {clasificacion['clase_nombre']}"
    
    if status_impi == "POSIBLEMENTE_DISPONIBLE":
        mensaje = f"¡Buenas noticias! No encontramos coincidencias exactas de '{marca}'."
        icono, color = "✓", "success"
        cta = "Se requiere un análisis fonético completo para confirmar disponibilidad."
    elif status_impi == "REQUIERE_ANALISIS":
        mensaje = f"Encontramos registros relacionados con '{marca}' en el IMPI."
        icono, color = "⚠️", "warning"
        cta = "Tu marca o una similar podría estar registrada."
    else:
        mensaje = f"No pudimos conectar con el IMPI."
        icono, color = "🔄", "info"
        cta = "Déjanos tus datos para búsqueda manual."
    
    return jsonify({
        "mensaje": mensaje,
        "icono": icono,
        "color": color,
        "clase_sugerida": clase_sugerida,
        "nota_tecnica": clasificacion.get('nota', ''),
        "mostrar_formulario": True,
        "cta": cta,
        "status_impi": status_impi,
        "tipo_negocio": tipo_negocio,
        "precio_reporte": PRECIO_REPORTE,
    })


@app.route('/capturar-lead', methods=['POST'])
def capturar_lead():
    """FORM 1: Captura lead inicial"""
    data = request.json
    
    datos_lead = {
        'fecha': datetime.now().strftime('%Y-%m-%d'),
        'hora': datetime.now().strftime('%H:%M:%S'),
        'nombre': data.get('nombre', ''),
        'email': data.get('email', ''),
        'telefono': data.get('telefono', ''),
        'marca': data.get('marca', ''),
        'tipo_negocio': data.get('tipo_negocio', ''),
        'clase_sugerida': data.get('clase_sugerida', ''),
        'status_impi': data.get('status_impi', ''),
        'pagado': 'NO',
    }
    
    if not all([datos_lead['nombre'], datos_lead['email'], datos_lead['telefono']]):
        return jsonify({"error": "Todos los campos son obligatorios"}), 400
    
    print(f"\n[LEAD] {datos_lead['nombre']} - {datos_lead['telefono']}")
    
    session['lead_data'] = datos_lead
    guardar_en_sheets(datos_lead, hoja="leads")
    
    # Enviar email en segundo plano para no bloquear
    threading.Thread(target=enviar_email_lead, args=(datos_lead.copy(),), daemon=True).start()
    
    return jsonify({
        "success": True,
        "mensaje": "¡Gracias! Hemos recibido tu información.",
        "mostrar_oferta": True,
        "oferta": {
            "titulo": "🎯 Obtén el Reporte Completo + Asesoría",
            "precio": PRECIO_REPORTE,
            "precio_formateado": f"${PRECIO_REPORTE:,} MXN",
            "beneficios": [
                "✓ Análisis fonético y fonográfico completo",
                "✓ Búsqueda exhaustiva de marcas similares",
                "✓ Reporte PDF profesional",
                "✓ Asesoría 1-a-1 por Google Meet (30 min)",
                "✓ Recomendaciones personalizadas"
            ],
            "link_pago": MERCADO_PAGO_LINK,
        },
    })


@app.route('/facturacion')
def facturacion():
    """FORM 2: Facturación post-pago"""
    lead_data = session.get('lead_data', {})
    telefono = lead_data.get('telefono', request.args.get('tel', ''))
    return render_template('facturacion.html', telefono=telefono, lead_data=lead_data)


@app.route('/guardar-facturacion', methods=['POST'])
def guardar_facturacion():
    """Guarda facturación"""
    data = request.json
    
    datos_fact = {
        'fecha': datetime.now().strftime('%Y-%m-%d'),
        'hora': datetime.now().strftime('%H:%M:%S'),
        'telefono': data.get('telefono', ''),
        'email': data.get('email', ''),
        'requiere_factura': data.get('requiere_factura', 'No'),
        'rfc': data.get('rfc', ''),
        'razon_social': data.get('razon_social', ''),
        'regimen_fiscal': data.get('regimen_fiscal', ''),
        'uso_cfdi': data.get('uso_cfdi', ''),
        'codigo_postal': data.get('codigo_postal', ''),
    }
    
    if not datos_fact['telefono'] or not datos_fact['email']:
        return jsonify({"error": "Teléfono y email obligatorios"}), 400
    
    guardar_en_sheets(datos_fact, hoja="facturacion")
    session['facturacion_data'] = datos_fact
    
    return jsonify({"success": True, "redirect": "/confirmacion"})


@app.route('/confirmacion')
def confirmacion():
    """Página final con calendario y WhatsApp"""
    lead_data = session.get('lead_data', {})
    fact_data = session.get('facturacion_data', {})
    telefono = fact_data.get('telefono', lead_data.get('telefono', ''))
    
    mensaje_wa = generar_mensaje_whatsapp(lead_data, fact_data)
    whatsapp_link = f"https://wa.me/{WHATSAPP_NUMERO}?text={quote(mensaje_wa)}"
    
    return render_template('confirmacion.html',
                         telefono=telefono,
                         cal_com_url=CAL_COM_URL,
                         whatsapp_link=whatsapp_link,
                         lead_data=lead_data)


@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "version": "funnel-2.0",
        "precio": PRECIO_REPORTE,
    })


@app.route('/debug/test/<marca>')
def debug_test(marca):
    return jsonify({"marca": marca, "resultado": buscar_impi_simple(marca)})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    print(f"\n{'='*70}")
    print(f"🌐 CONSULTOR DE MARCAS - FUNNEL v2.0")
    print(f"URL: {APP_BASE_URL}")
    print(f"Precio: ${PRECIO_REPORTE} MXN")
    print(f"{'='*70}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
