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
        
        # Prompt ULTRA simplificado
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
                max_output_tokens=100,
            )
        )
        
        text = response.text.strip()
        print(f"[GEMINI DEBUG] Respuesta: {text}")
        
        # Parsear formato simple CLASE|NOMBRE|NOTA
        if '|' in text:
            partes = text.split('|')
            if len(partes) >= 3:
                clase = partes[0].strip()
                nombre = partes[1].strip()
                nota = partes[2].strip()
                
                # Extraer solo el número de la clase
                match = re.search(r'\d+', clase)
                if match:
                    clase_num = match.group()
                else:
                    clase_num = clase
                
                resultado = {
                    "clase_principal": clase_num,
                    "clase_nombre": nombre,
                    "clases_adicionales": [],
                    "nota": nota
                }
                
                print(f"[GEMINI] ✓ Clase: {clase_num} - {nombre}")
                return resultado
        
        # Si no pudo parsear, intentar extraer número
        numeros = re.findall(r'\b\d{1,2}\b', text)
        if numeros:
            clase_num = numeros[0]
            resultado = {
                "clase_principal": clase_num,
                "clase_nombre": f"Clase {clase_num}",
                "clases_adicionales": [],
                "nota": text[:100]
            }
            print(f"[GEMINI] ⚠ Clase extraída: {clase_num}")
            return resultado
        
        raise ValueError("No se pudo extraer clase de Niza")
        
    except Exception as e:
        print(f"[ERROR GEMINI] {e}")
        # Fallback inteligente
        if tipo_negocio.lower() == 'producto':
            if any(kw in descripcion.lower() for kw in ['bebida', 'refresco', 'agua', 'jugo']):
                return {"clase_principal": "32", "clase_nombre": "Bebidas", "clases_adicionales": [], "nota": "Clasificación automática"}
            elif any(kw in descripcion.lower() for kw in ['comida', 'alimento', 'snack']):
                return {"clase_principal": "29", "clase_nombre": "Alimentos", "clases_adicionales": [], "nota": "Clasificación automática"}
            elif any(kw in descripcion.lower() for kw in ['ropa', 'vestido', 'calzado']):
                return {"clase_principal": "25", "clase_nombre": "Ropa y calzado", "clases_adicionales": [], "nota": "Clasificación automática"}
            elif any(kw in descripcion.lower() for kw in ['software', 'app', 'programa', 'tecnolog']):
                return {"clase_principal": "9", "clase_nombre": "Software y tecnología", "clases_adicionales": [], "nota": "Clasificación automática"}
            else:
                return {"clase_principal": "1", "clase_nombre": "Productos varios", "clases_adicionales": [], "nota": "Clasificación por defecto"}
        else:
            if any(kw in descripcion.lower() for kw in ['restaurante', 'cafetería', 'bar', 'comida', 'café']):
                return {"clase_principal": "43", "clase_nombre": "Servicios de restauración", "clases_adicionales": [], "nota": "Clasificación automática"}
            elif any(kw in descripcion.lower() for kw in ['software', 'desarrollo', 'tecnolog', 'it', 'sistemas']):
                return {"clase_principal": "42", "clase_nombre": "Servicios tecnológicos", "clases_adicionales": [], "nota": "Clasificación automática"}
            else:
                return {"clase_principal": "35", "clase_nombre": "Servicios comerciales", "clases_adicionales": [], "nota": "Clasificación por defecto"}

def buscar_impi_simple(marca):
    """Búsqueda SIMPLE por denominación en el IMPI"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-MX,es;q=0.9',
        'Referer': 'https://acervomarcas.impi.gob.mx:8181/marcanet/'
    })
    
    try:
        marca_norm = normalizar_marca(marca)
        print(f"\n[IMPI SIMPLE] Buscando: '{marca_norm}'")
        
        variantes = [
            marca_norm,
            marca_norm.replace(' ', '-'),
            marca_norm.replace(' ', ''),
        ]
        
        for variante in variantes:
            try:
                print(f"[IMPI] Probando variante: '{variante}'")
                
                url_base = "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/datos/bsqDenominacionCompleto.pgi"
                response = session.get(url_base, timeout=20)
                
                if response.status_code != 200:
                    continue
                
                time.sleep(1)
                
                data = {'denominacion': variante}
                response = session.post(url_base, data=data, timeout=25)
                
                texto = response.text.lower()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                tablas = soup.find_all('table')
                if tablas and len(tablas) > 0:
                    for tabla in tablas:
                        filas = tabla.find_all('tr')
                        if len(filas) > 1:
                            print(f"[IMPI] ✗ Tabla con resultados encontrada")
                            return "REQUIERE_ANALISIS"
                
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
                
                sin_resultados = [
                    'no se encontraron registros',
                    'sin resultados',
                    '0 resultados',
                    'búsqueda sin resultados'
                ]
                
                if any(msg in texto for msg in sin_resultados):
                    print(f"[IMPI] ✓ Sin resultados para '{variante}'")
                    continue
                
            except Exception as e:
                print(f"[IMPI] Error con variante '{variante}': {e}")
                continue
        
        print(f"[IMPI] ✓ No se encontraron coincidencias")
        return "POSIBLEMENTE_DISPONIBLE"
        
    except Exception as e:
        print(f"[IMPI] Error general: {e}")
        return "REQUIERE_ANALISIS"

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
                    <p style="margin: 0; color: #4a5568;"><strong>Mensaje mostrado al cliente:</strong></p>
                    <p style="margin: 10px 0 0 0; color: #2d3748;">{datos_lead['resultado']}</p>
                </div>
                
                <p style="color: #718096; font-size: 12px; margin-top: 30px; text-align: center;">
                    📅 {datos_lead['fecha']} a las {datos_lead['hora']}<br>
                    Enviado desde Consultor de Marcas | MarcaSegura
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

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/analizar', methods=['POST'])
def analizar():
    """Endpoint principal - VERSIÓN PÚBLICA"""
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
    
    # 2. Búsqueda simple en IMPI
    status_impi = buscar_impi_simple(marca)
    
    # 3. Preparar respuesta
    if status_impi == "POSIBLEMENTE_DISPONIBLE":
        mensaje = f"¡Buenas noticias! No encontramos coincidencias exactas de '{marca}' en nuestra búsqueda preliminar."
        icono = "✓"
        color = "success"
        cta = "Sin embargo, esto NO garantiza disponibilidad total. Se requiere un análisis fonético y fonográfico completo por un especialista para verificar todas las variantes posibles. Déjanos tus datos para realizar el estudio técnico profesional."
        
    elif status_impi == "REQUIERE_ANALISIS":
        mensaje = f"Tu marca '{marca}' o una parecida parece estar registrada."
        icono = "⚠️"
        color = "warning"
        cta = "Agenda una consulta con nuestro ejecutivo para analizar alternativas disponibles y encontrar el nombre perfecto para tu negocio. Déjanos tus datos y te contactaremos dentro de 24 horas."
        
    else:
        mensaje = f"No pudimos completar la búsqueda de '{marca}' en este momento."
        icono = "🔍"
        color = "info"
        cta = "Por favor intenta nuevamente o déjanos tus datos para realizar la búsqueda manualmente y contactarte con los resultados en menos de 24 horas."
    
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
    """Captura el lead"""
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
    
    guardar_lead_google_sheets(datos_lead)
    enviar_email_lead(datos_lead)
    
    from urllib.parse import quote
    titulo = f"Consulta de Marca - {datos_lead['nombre']}"
    desc = f"Análisis para la marca: {datos_lead['marca']}"
    calendar_link = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={quote(titulo)}&details={quote(desc)}"
    
    return jsonify({
        "success": True,
        "mensaje": "¡Gracias! Hemos recibido tu información.",
        "calendar_link": calendar_link
    })

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
