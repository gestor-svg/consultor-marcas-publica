import os
import requests
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
import google.generativeai as genai
import json
from functools import lru_cache
import time
from datetime import datetime
import re

app = Flask(__name__)

# --- CONFIGURACIÓN ---
API_KEY_GEMINI = os.environ.get("API_KEY_GEMINI")
GOOGLE_APPS_SCRIPT_URL = os.environ.get("GOOGLE_APPS_SCRIPT_URL")  # URL del Apps Script
GMAIL_USER = os.environ.get("GMAIL_USER")  # Tu email de Gmail
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")  # Contraseña de aplicación
EMAIL_DESTINO = "gestor@marcasegura.com.mx"

if API_KEY_GEMINI:
    genai.configure(api_key=API_KEY_GEMINI)
    print("✓ Gemini configurado")
else:
    print("⚠ API_KEY_GEMINI no encontrada")

def normalizar_marca(marca):
    """Normaliza el nombre de la marca"""
    marca = marca.upper().strip()
    marca = re.sub(r'[^\w\s\-]', '', marca)
    marca = re.sub(r'\s+', ' ', marca)
    return marca

@lru_cache(maxsize=100)
def clasificar_con_gemini(descripcion, tipo_negocio):
    """
    Usa Gemini para determinar la clase de Niza según el giro
    tipo_negocio: 'producto' o 'servicio'
    """
    if not API_KEY_GEMINI:
        return {
            "clase_principal": "35",
            "clase_nombre": "Servicios comerciales",
            "clases_adicionales": [],
            "nota": "Configuración de IA pendiente"
        }
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""Eres un experto en clasificación de marcas según el sistema de Niza de la OMPI.

Analiza este negocio:
- Descripción: {descripcion}
- Tipo: {tipo_negocio}

Responde ÚNICAMENTE con un objeto JSON válido (sin markdown):
{{
  "clase_principal": "XX",
  "clase_nombre": "Descripción corta de la clase",
  "clases_adicionales": ["YY", "ZZ"],
  "nota": "Breve explicación de por qué esta clase"
}}

Recuerda:
- Productos: Clases 1-34
- Servicios: Clases 35-45
- Sé específico y preciso"""

        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.2,  # Más determinista
                max_output_tokens=1024,  # Aumentado aún más
            )
        )
        
        text = response.text.strip()
        print(f"[GEMINI DEBUG] Respuesta cruda: {repr(text)[:300]}")
        
        # Limpiar markdown
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                if '{' in part:
                    text = part.replace("json", "").replace("JSON", "").strip()
                    break
        
        # Limpiar TODOS los caracteres problemáticos
        text = text.replace('\n', ' ')
        text = text.replace('\r', ' ')
        text = text.replace('\t', ' ')
        text = text.replace('\\n', ' ')
        text = text.replace('\\r', ' ')
        text = text.replace('\\t', ' ')
        
        # Quitar espacios múltiples
        import re
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Buscar el JSON válido
        start = text.find('{')
        end = text.rfind('}') + 1
        
        if start >= 0 and end > start:
            text = text[start:end]
        else:
            raise ValueError("No se encontró JSON válido en la respuesta")
        
        # PLAN B: Si falta la llave de cierre, agregarla
        if text.count('{') > text.count('}'):
            text += '}'
        
        # PLAN B: Si tiene comillas sin cerrar, limpiar
        # Contar comillas dobles
        if text.count('"') % 2 != 0:
            # Quitar la última comilla impar
            last_quote = text.rfind('"')
            text = text[:last_quote]
            text += '}'
        
        print(f"[GEMINI DEBUG] JSON limpio: {text[:300]}")
        
        # Intentar parsear
        resultado = json.loads(text)
        print(f"[GEMINI] ✓ Clase sugerida: {resultado['clase_principal']}")
        return resultado
        print(f"[GEMINI] Clase sugerida: {resultado['clase_principal']} - {resultado['clase_nombre']}")
        return resultado
        
    except Exception as e:
        print(f"[ERROR GEMINI] {e}")
        # Fallback según tipo
        if tipo_negocio.lower() == 'producto':
            return {
                "clase_principal": "9",
                "clase_nombre": "Productos tecnológicos y científicos",
                "clases_adicionales": ["35"],
                "nota": "Clasificación por defecto para productos"
            }
        else:
            return {
                "clase_principal": "35",
                "clase_nombre": "Servicios comerciales y publicidad",
                "clases_adicionales": ["42"],
                "nota": "Clasificación por defecto para servicios"
            }

def buscar_impi_simple(marca):
    """
    Búsqueda SIMPLE por denominación en el IMPI
    Versión mejorada - acepta que si encuentra ALGO es mejor decir "requiere análisis"
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-MX,es;q=0.9',
        'Referer': 'https://acervomarcas.impi.gob.mx:8181/marcanet/'
    })
    
    try:
        marca_norm = normalizar_marca(marca)
        print(f"\n[IMPI SIMPLE] Buscando: '{marca_norm}'")
        
        # Probamos múltiples variantes de la marca
        variantes = [
            marca_norm,
            marca_norm.replace(' ', '-'),
            marca_norm.replace(' ', ''),
        ]
        
        for variante in variantes:
            try:
                print(f"[IMPI] Probando variante: '{variante}'")
                
                # URL de búsqueda
                url_base = "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/datos/bsqDenominacionCompleto.pgi"
                
                response = session.get(url_base, timeout=20)
                
                if response.status_code != 200:
                    continue
                
                time.sleep(1)
                
                # Intentar POST
                data = {'denominacion': variante}
                response = session.post(url_base, data=data, timeout=25)
                
                texto = response.text.lower()
                
                # Analizamos más cuidadosamente
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Buscar tablas (si hay tabla, hay resultados)
                tablas = soup.find_all('table')
                if tablas and len(tablas) > 0:
                    # Verificar que la tabla tenga contenido real
                    for tabla in tablas:
                        filas = tabla.find_all('tr')
                        if len(filas) > 1:  # Más de solo encabezado
                            print(f"[IMPI] ✗ Tabla con resultados encontrada")
                            return "REQUIERE_ANALISIS"
                
                # Buscar keywords más específicos
                keywords_encontrada = [
                    'expediente',
                    'solicitud',
                    'registro',
                    'titular',
                    'vigente',
                    'en trámite'
                ]
                
                if any(kw in texto for kw in keywords_encontrada):
                    print(f"[IMPI] ✗ Keywords de registro encontrados")
                    return "REQUIERE_ANALISIS"
                
                # Mensajes explícitos de "sin resultados"
                sin_resultados = [
                    'no se encontraron registros',
                    'sin resultados',
                    '0 resultados',
                    'búsqueda sin resultados'
                ]
                
                if any(msg in texto for msg in sin_resultados):
                    print(f"[IMPI] ✓ Sin resultados para '{variante}'")
                    continue  # Probar siguiente variante
                
            except Exception as e:
                print(f"[IMPI] Error con variante '{variante}': {e}")
                continue
        
        # Si llegamos aquí, no encontramos nada en ninguna variante
        print(f"[IMPI] ✓ No se encontraron coincidencias en ninguna variante")
        return "POSIBLEMENTE_DISPONIBLE"
        
    except Exception as e:
        print(f"[IMPI] Error general: {e}")
        return "REQUIERE_ANALISIS"  # Ante duda, mejor pedir análisis

def guardar_lead_google_sheets(datos_lead):
    """Guarda el lead en Google Sheets mediante Apps Script"""
    # URL del Google Apps Script (se configura como variable de entorno)
    APPS_SCRIPT_URL = os.environ.get("GOOGLE_APPS_SCRIPT_URL")
    
    if not APPS_SCRIPT_URL:
        print("⚠ Google Apps Script URL no configurada")
        return False
    
    try:
        # Enviar datos al Apps Script
        response = requests.post(
            APPS_SCRIPT_URL,
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
    """Envía email con los datos del lead usando Gmail SMTP"""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("⚠ Gmail SMTP no configurado")
        return False
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Preparar email HTML
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
                    <p style="margin: 0; color: #4a5568;"><strong>Mensaje mostrado al cliente:</strong></p>
                    <p style="margin: 10px 0 0 0; color: #2d3748;">{datos_lead['resultado']}</p>
                </div>
                
                <div style="margin-top: 30px; padding: 20px; background: #e6fffa; border-radius: 10px; border-left: 4px solid #38b2ac;">
                    <p style="margin: 0; color: #234e52;"><strong>📞 Acciones sugeridas:</strong></p>
                    <ul style="margin: 10px 0 0 0; padding-left: 20px; color: #234e52;">
                        <li>Contactar al cliente dentro de las próximas 24 horas</li>
                        <li>Preparar análisis técnico completo de la marca</li>
                        <li>Revisar antecedentes en IMPI manualmente</li>
                    </ul>
                </div>
                
                <p style="color: #718096; font-size: 12px; margin-top: 30px; text-align: center;">
                    📅 {datos_lead['fecha']} a las {datos_lead['hora']}<br>
                    Enviado desde Consultor de Marcas | MarcaSegura
                </p>
            </div>
        </body>
        </html>
        """
        
        # Versión texto plano (fallback)
        texto_plano = f"""
NUEVO LEAD CAPTURADO

DATOS DEL CLIENTE:
- Nombre: {datos_lead['nombre']}
- Email: {datos_lead['email']}
- Teléfono: {datos_lead['telefono']}

CONSULTA:
- Marca: {datos_lead['marca']}
- Tipo de negocio: {datos_lead['tipo_negocio']}
- Status IMPI: {datos_lead['status_impi']}

MENSAJE MOSTRADO:
{datos_lead['resultado']}

Fecha: {datos_lead['fecha']} {datos_lead['hora']}
        """
        
        # Crear mensaje
        mensaje = MIMEMultipart('alternative')
        mensaje['Subject'] = f"🎯 Nuevo Lead - {datos_lead['nombre']} | Marca: {datos_lead['marca']}"
        mensaje['From'] = GMAIL_USER
        mensaje['To'] = EMAIL_DESTINO
        
        # Adjuntar ambas versiones
        parte_texto = MIMEText(texto_plano, 'plain', 'utf-8')
        parte_html = MIMEText(html_content, 'html', 'utf-8')
        
        mensaje.attach(parte_texto)
        mensaje.attach(parte_html)
        
        # Conectar a Gmail SMTP
        print(f"[EMAIL] Conectando a Gmail SMTP...")
        servidor = smtplib.SMTP('smtp.gmail.com', 587)
        servidor.starttls()
        servidor.login(GMAIL_USER, GMAIL_PASSWORD)
        
        # Enviar
        servidor.send_message(mensaje)
        servidor.quit()
        
        print(f"[EMAIL] ✓ Email enviado correctamente a {EMAIL_DESTINO}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        print(f"[EMAIL] ✗ Error de autenticación - Verifica usuario y contraseña de aplicación")
        return False
    except Exception as e:
        print(f"[EMAIL] ✗ Error: {e}")
        return False

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/analizar', methods=['POST'])
def analizar():
    """
    Endpoint principal - VERSIÓN PÚBLICA
    Usa búsqueda simple del IMPI + Gemini
    """
    data = request.json
    marca = data.get('marca', '').strip()
    descripcion = data.get('descripcion', '').strip()
    tipo_negocio = data.get('tipo', 'servicio').lower()
    
    if not marca or not descripcion:
        return jsonify({"error": "Marca y descripción son obligatorias"}), 400
    
    print(f"\n{'='*70}")
    print(f"ANÁLISIS DE MARCA - Versión Pública")
    print(f"Marca: {marca}")
    print(f"Tipo: {tipo_negocio}")
    print(f"{'='*70}")
    
    # 1. Clasificar con Gemini
    clasificacion = clasificar_con_gemini(descripcion, tipo_negocio)
    
    # 2. Búsqueda simple en IMPI (solo denominación exacta)
    status_impi = buscar_impi_simple(marca)
    
    # 3. Preparar respuesta según resultado
    if status_impi == "POSIBLEMENTE_DISPONIBLE":
        mensaje = f"Preliminar: No encontramos coincidencias exactas de '{marca}' en nuestra búsqueda básica del IMPI."
        icono = "🔍"
        color = "success"
        cta = "Sin embargo, esto NO garantiza disponibilidad. Se requiere un análisis fonético y fonográfico completo por un especialista. Déjanos tus datos para realizar el estudio técnico profesional que incluye búsqueda en todas las variantes y clases."
        
    else:  # REQUIERE_ANALISIS o ERROR
        mensaje = f"La marca '{marca}' requiere análisis técnico profesional detallado."
        icono = "⚠️"
        color = "warning"
        cta = "Nuestra búsqueda preliminar indica posibles conflictos o no pudo completarse. Para verificar similitudes fonéticas, gráficas y en todas las clases relevantes, déjanos tus datos. Te contactaremos dentro de 24 horas con un reporte completo."
    
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
    
    print(f"[RESULTADO] Status: {status_impi}, Clase: {clasificacion['clase_principal']}")
    print(f"{'='*70}\n")
    
    return jsonify(resultado)

@app.route('/capturar-lead', methods=['POST'])
def capturar_lead():
    """
    Endpoint para capturar el lead después de mostrar el resultado
    """
    data = request.json
    
    # Datos del formulario
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
    
    # Validar datos obligatorios
    if not all([datos_lead['nombre'], datos_lead['email'], datos_lead['telefono']]):
        return jsonify({"error": "Todos los campos son obligatorios"}), 400
    
    print(f"\n[LEAD CAPTURADO] {datos_lead['nombre']} - {datos_lead['marca']}")
    
    # Guardar en Google Sheets
    sheets_ok = guardar_lead_google_sheets(datos_lead)
    
    # Enviar email
    email_ok = enviar_email_lead(datos_lead)
    
    # Link de Google Calendar
    calendar_link = generar_link_google_calendar(datos_lead['nombre'], datos_lead['marca'])
    
    return jsonify({
        "success": True,
        "mensaje": "¡Gracias! Hemos recibido tu información.",
        "calendar_link": calendar_link
    })

def generar_link_google_calendar(nombre, marca):
    """Genera link para agregar cita a Google Calendar"""
    # Formato: https://calendar.google.com/calendar/render?action=TEMPLATE&text=...
    
    titulo = f"Consulta de Marca - {nombre}"
    descripcion = f"Análisis y estrategia de registro para la marca: {marca}"
    
    # Codificar para URL
    from urllib.parse import quote
    titulo_encoded = quote(titulo)
    desc_encoded = quote(descripcion)
    
    # Link básico (el usuario elige fecha/hora)
    link = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={titulo_encoded}&details={desc_encoded}"
    
    return link

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "version": "publica-1.0",
        "gemini": bool(API_KEY_GEMINI),
        "sheets": bool(GOOGLE_APPS_SCRIPT_URL),
        "email": bool(GMAIL_USER and GMAIL_PASSWORD)
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    print(f"\n{'='*70}")
    print(f"🌐 CONSULTOR DE MARCAS - VERSIÓN PÚBLICA")
    print(f"{'='*70}")
    print(f"Puerto: {port}")
    print(f"Gemini: {'✓' if API_KEY_GEMINI else '✗'}")
    print(f"Google Sheets: {'✓' if GOOGLE_APPS_SCRIPT_URL else '✗'}")
    print(f"Gmail SMTP: {'✓' if (GMAIL_USER and GMAIL_PASSWORD) else '✗'}")
    print(f"{'='*70}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
