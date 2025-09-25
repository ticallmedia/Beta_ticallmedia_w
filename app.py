from flask import Flask, request, json, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import http.client
import logging
import os
from dotenv import load_dotenv
import openai
from prompt_ia import get_message
from io import StringIO # Importar StringIO para el manejo de credenciales
import threading
import psycopg2
from langdetect import detect #detecta idioma

load_dotenv()
#_______________________________________________________________________________________
"""
Version 3:
Descripción: Primer Bot de Whatsapp para la empresa TicAll Media, 
integrado con IA de OpenAI

Caracteristicas: 

- AI gpt-3.5-turbo inicialmente, en python con openai==0.28.1
- En gitgnore, se agrega el archivo .env
- Las credenciales se suben en render directamente
- Se actualiza presentación del portafolio como Lista, y prompt invoca lista no la genera
- Se actualiza estado del usuario, para su categorización como posible cliente

Actualiza 15/07/2025:
-Se cambia bd SQLite a PostgreSQl para mejorar la persistencia de los datos
-Tambien para utilizar mas de Una API para consultar la misma fuente de datos

Actualiza 05/08/2025:
-Se agrega la libreria 'langdetect', con el fin de poder identificar el idioma del usuario
-Se crean las funciones: actualizar_idioma_si_cambia, guardar_idioma_usuario, obtener_idioma_usuario, detectar_idioma  
para guardar, actualiza y obtener el idioma
-se crea la tabal 'UsuarioLang' para capturar el idioma
-se actualizan funciones para que siempre soliciten idioma

"""
#_______________________________________________________________________________________
app = Flask(__name__)

# Configura el logger (Log de eventos para ajustado para utilizarlo en render)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuración de base de datos SQLITE
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Creación tabla, o modelado
class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha_y_hora = db.Column(db.DateTime, default=datetime.utcnow)
    telefono_usuario_id = db.Column(db.Text)
    plataforma = db.Column(db.Text)
    mensaje = db.Column(db.Text)
    estado_usuario = db.Column(db.Text)
    etiqueta_campana = db.Column(db.Text)
    agente = db.Column(db.Text)

class UsuarioLang(db.Model):
    telefono_usuario_id = db.Column(db.Text, primary_key=True) #es ell mismo whatsapp_id
    lang = db.Column(db.Text)

class UsuariosBot(db.Model):
    id_bot = db.Column(db.Integer, primary_key=True)
    lang = db.Column(db.Text)
    telefono_usuario_id = db.Column(db.Text) #es ell mismo whatsapp_id
    crm_contact_id = db.Column(db.Text)
    nombre_preferido = db.Column(db.Text)
    estado_usuario = db.Column(db.Text)
    fecha_y_hora = db.Column(db.DateTime, default=datetime.utcnow)

# Crear tabla si no existe
with app.app_context():
    db.create_all()
    logging.info(f"Creación de tablas usuario y de conversacion...")
#_______________________________________________________________________________________

# --- Recursos ---
IMA_SALUDO_URL = "https://res.cloudinary.com/dioy4cydg/image/upload/v1747884690/imagen_index_wjog6p.jpg"
AGENTE_BOT = "Bot" # Usamos una constante para el agente
ESTADO_USUARIO = ""
#_______________________________________________________________________________________
# --- Funciones de la Aplicación Flask ---
@app.route('/')
def index():
    """Renderiza la página principal con los registros del log."""
    registros = Log.query.all()
    registros_ordenados = sorted(registros, key=lambda x: x.fecha_y_hora, reverse=True)
    return render_template('index.html', registros=registros_ordenados)

def agregar_mensajes_log(datos_json):
    """Agrega un registro de mensaje a la base de datos."""
    datos = json.loads(datos_json)
    nuevo_registro = Log(
        telefono_usuario_id=datos.get('telefono_usuario_id'),
        plataforma=datos.get('plataforma'),
        mensaje=datos.get('mensaje'),
        estado_usuario=datos.get('estado_usuario'),
        etiqueta_campana=datos.get('etiqueta_campana'),
        agente=datos.get('agente')
    )
    db.session.add(nuevo_registro)
    db.session.commit()


def _agregar_mensajes_log_thread_safe(log_data_json):
    """Función para agregar un registro a la base de datos en un hilo."""
    with app.app_context(): # Necesario para interactuar con SQLAlchemy en un hilo
        try:
            datos = json.loads(log_data_json)
            nuevo_registro = Log(
                telefono_usuario_id=datos.get('telefono_usuario_id'),
                plataforma=datos.get('plataforma'),
                mensaje=datos.get('mensaje'),
                estado_usuario=datos.get('estado_usuario'),
                etiqueta_campana=datos.get('etiqueta_campana'),
                agente=datos.get('agente')
            )
            db.session.add(nuevo_registro)
            db.session.commit()
            logging.info(f"Registro de log añadido a DB (hilo): {datos.get('mensaje')}")
        except Exception as e:
            db.session.rollback() # Si hay un error, revertir la transacción
            logging.error(f"Error añadiendo log a DB (hilo): {e}")


def guardar_idioma_usuario(telefono_usuario_id, idioma):
    #Guarda o actualiza el idioma del usuario.
    usuario = UsuarioLang.query.filter_by(telefono_usuario_id=telefono_usuario_id).first()
    if usuario:
        usuario.lang = idioma
    else:
        usuario = UsuarioLang(telefono_usuario_id=telefono_usuario_id, lang=idioma)
        db.session.add(usuario)
    db.session.commit()

def obtener_idioma_usuario(telefono_usuario_id):
    usuario = UsuarioLang.query.filter_by(telefono_usuario_id=telefono_usuario_id).first()
    if usuario:
        logging.info(f"El idioma del usuario {telefono_usuario_id}  es: {usuario.lang}")
        return usuario.lang
    logging.info(f"El usuario {telefono_usuario_id} no tiene idioma se le asiga: es")
    return 'es'

def actualizar_idioma_si_cambia(telefono_usuario_id, mensaje):
    """Detecta y actualiza el idioma del usuario si cambió."""
    idioma_detectado = detectar_idioma(mensaje)
    idioma_actual = obtener_idioma_usuario(telefono_usuario_id)

    if idioma_detectado != idioma_actual:        
        guardar_idioma_usuario(telefono_usuario_id, idioma_detectado)
        logging.info(f"Actualiza idioma del usuario {telefono_usuario_id} como: {idioma_detectado}")
    
    logging.info(f"El idioma del usuario {telefono_usuario_id} no cambio, es: {idioma_detectado}")
    return idioma_detectado

# --- detecta el idioma si es español o ingles ---
def detectar_idioma(texto):
    try:
        idioma = detect(texto)
        if idioma == 'es':
            return 'es' #español
        elif idioma == 'en':
            return 'en' #ingles
        else:
            return 'en'
    except:
        return 'en' #por defecto español
    

# --- API WhatsApp para el envío de mensajes ---
def send_whatsapp_message(data):
    """Envía un mensaje a través de la API de WhatsApp Business."""
    data = json.dumps(data)

    #se agrega la codificación utf-8 para que las listas pasen sin problema
    encoded_data = data.encode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ['META_WHATSAPP_ACCESS_TOKEN']}"
    }

    connection = http.client.HTTPSConnection("graph.facebook.com")
    try:
        connection.request("POST", f"/{os.environ['API_WHATSAPP_VERSION']}/{os.environ['META_WHATSAPP_PHONE_NUMBER_ID']}/messages", encoded_data, headers)
        response = connection.getresponse()
        logging.info(f"Respuesta de WhatsApp API: {response.status} {response.reason}")
    except Exception as e:
        logging.error(f"Error al enviar mensaje a WhatsApp: {e}")
        # No se registra aquí en la DB para evitar redundancia, se registra antes de llamar a esta función
    finally:
        connection.close()

""""Función para cargar o actualizar prompt de la IA, y mantener el hilo de
conversación con un usuario"""

# Diccionarios de control
user_profiles = {}   # datos fijos del usuario (nombre, gustos, etc.)
user_histories = {}  # historial de la conversación
user_languages = {}  # idioma actual por usuario

def send_ia_prompt(prompt,telefono_id,lang):
    try:
        openai.api_key = os.environ.get("OPENAI_API_KEY")
        message_prompt = get_message(lang, prompt)

        """"
        #version 1

        #permite recordar la conversacion con el usuario, pero no permite refrescar el idioma
        if telefono_id not in user_histories:
            user_histories[telefono_id] = [
                {"role": "system", "content": message_prompt},
                {"role": "system", "content": f"Please always respond in '{lang}' language."}
                ]
        """
        """
        #No recuerda la conversacion del usuario y permite refrescar el idioma
        user_histories[telefono_id] = [
            {"role": "system", "content": message_prompt},
            {"role": "system", "content": f"Please always respond in '{lang}' language."}
            ]
        """
        """
        #version 2
        # Si ya hay historial, actualiza el primer mensaje si es de tipo 'system'
        if telefono_id in user_histories:
            # Reemplazar el primer system prompt (o agregar si no está)
            user_histories[telefono_id][0] = {"role": "system", "content": message_prompt}
            
            # Verifica si hay un segundo mensaje indicando el idioma
            if len(user_histories[telefono_id]) > 1 and user_histories[telefono_id][1]['role'] == "system":
                user_histories[telefono_id][1] = {"role": "system", "content": f"Please always respond in '{lang}' language."}
            else:
                user_histories[telefono_id].insert(1, {"role": "system", "content": f"Please always respond in '{lang}' language."})
        else:
            # No hay historial, lo creamos
            user_histories[telefono_id] = [
                {"role": "system", "content": message_prompt},
                {"role": "system", "content": f"Please always respond in '{lang}' language."}
                ]
        
        """

        #version 3

        """Actualiza el prompt e idioma del usuario, manteniendo su perfil fijo."""
        # Obtiene perfil si existe
        perfil = user_profiles.get(telefono_id, {})

        # Si el idioma cambió o no hay historial → reinicia historial
        if telefono_id not in user_histories or user_languages.get(telefono_id) != lang:
            user_histories[telefono_id] = [
                {"role": "system", "content": message_prompt},
                {"role": "system", "content": f"Please always respond in '{lang}' language."},
                {"role": "system", "content": f"User profile: {perfil}"}
            ]
            user_languages[telefono_id] = lang

        else:
            # Si el idioma no cambió → actualiza prompts en el historial existente
            user_histories[telefono_id][0] = {"role": "system", "content": message_prompt} #carga el prompt

            if len(user_histories[telefono_id]) > 1 and user_histories[telefono_id][1]['role'] == "system":
                user_histories[telefono_id][1] = {"role": "system", "content": f"Please always respond in '{lang}' language."}
            else:
                user_histories[telefono_id].insert(1, {"role": "system", "content": f"Please always respond in '{lang}' language."})

            # Actualiza o reinyecta el perfil si ya existe
            if perfil:
                if len(user_histories[telefono_id]) < 3 or user_histories[telefono_id][2]['role'] != "system":
                    user_histories[telefono_id].append({"role": "system", "content": f"User profile: {perfil}"})
                else:
                    user_histories[telefono_id][2] = {"role": "system", "content": f"User profile: {perfil}"}


        logging.info(f"Consulta a la IA: {user_histories}")
    except Exception as e:
        logging.error(f"Error con la IA: {e}")

    return list(user_histories[telefono_id])

"""Función que mantenie el flujo de la conversación de la IA"""

def send_ia_message(ESTADO_USUARIO, telefono_id, message_text, chat_history_prompt, lang):
    openai.api_key = os.environ.get("OPENAI_API_KEY")
    
    # 1. Si el usuario solicita ver el portafolio
    if message_text in ["portafolio", "ver servicios", "mostrar opciones", "servicios"]:
        request1_messages(telefono_id, lang)
        return

    # 2. Cargar historial si ya existe o iniciarlo con prompt
    if telefono_id not in user_histories:
        user_histories[telefono_id] = chat_history_prompt

    chat_history = user_histories[telefono_id]
    
    # Agregar el mensaje del usuario al historial
    chat_history.append({"role": "user", "content": message_text})

    try:
        # Solicitar respuesta a OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=chat_history
        )

        # Obtener la respuesta del asistente
        respuesta_bot = response['choices'][0]['message']['content']
        #print(f"Asistente: {respuesta_bot}\n")

        # Agregar respuesta del bot al historial
        chat_history.append({"role": "assistant", "content": respuesta_bot})

        send_message_and_log(lang,ESTADO_USUARIO,telefono_id, respuesta_bot, 'text')

        logging.info(f"Consulta a la IA: {respuesta_bot}")
    except Exception as e:
        logging.error(f"Error con la IA: {e}")
#_______________________________________________________________________________________
# --- Uso del Token y recepción de mensajes ---
TOKEN_CODE = os.getenv('META_WHATSAPP_TOKEN_CODE')

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """Maneja las solicitudes GET y POST del webhook de WhatsApp."""
    if request.method == 'GET':
        challenge = verificar_token(request)
        return challenge
    elif request.method == 'POST':
        response = recibir_mensajes(request)
        return response

def verificar_token(req):
    """Verifica el token de verificación de WhatsApp."""
    token = req.args.get('hub.verify_token')
    challenge = req.args.get('hub.challenge')

    if challenge and token == TOKEN_CODE:
        return challenge
    else:
        return jsonify({'error': 'Token Invalido'}), 401

def recibir_mensajes(req):
    """Procesa los mensajes entrantes del webhook de WhatsApp."""
    try:
        data_json = req.get_json()
        logging.info(f"Mensaje recibido: {json.dumps(data_json, indent=2)}")

        entry = data_json.get('entry', [{}])[0]
        changes = entry.get('changes', [{}])[0]
        value = changes.get('value', {})
        objeto_mensaje = value.get('messages', [])

        if objeto_mensaje:
            message = objeto_mensaje[0]
            telefono_id = message.get('from')
            tipo_mensaje = message.get('type')
            
            mensaje_texto = ""
            if tipo_mensaje == 'interactive':
                interactive_type = message.get('interactive', {}).get('type')
                if interactive_type == "button_reply":
                    mensaje_texto = message.get('interactive', {}).get('button_reply', {}).get('id')
                elif interactive_type == "list_reply":
                    mensaje_texto = message.get('interactive', {}).get('list_reply', {}).get('id')
            elif tipo_mensaje == 'text':
                mensaje_texto = message.get('text', {}).get('body')

            if telefono_id and mensaje_texto:

                chat_history = [{"role": "system", "content": mensaje_texto}]    

                procesar_y_responder_mensaje(telefono_id, mensaje_texto)
            else:
                logging.info("Mensaje no procesable (sin ID de teléfono o texto de mensaje).")
        
        return jsonify({'message': 'EVENT_RECEIVED'}), 200
    except Exception as e:
        logging.error(f"Error en recibir_mensajes: {e}")
        return jsonify({'message': 'EVENT_RECEIVED_ERROR'}), 500

def procesar_y_responder_mensaje(telefono_id, mensaje_recibido):
    """
    Procesa un mensaje recibido, determina el idioma del usuario y envía la respuesta adecuada.
    Registra el mensaje entrante y la respuesta en la base de datos y Google Sheets.
    """
    mensaje_procesado = mensaje_recibido.lower()
    user_language = ""
    
    # Primero, registra el mensaje entrante
    log_data_in = {
        'telefono_usuario_id': telefono_id,
        'plataforma': 'whatsapp 📞📱💬',
        'mensaje': mensaje_recibido,
        'estado_usuario': 'recibido',
        'etiqueta_campana': 'Vacaciones',
        'agente': AGENTE_BOT
    }

    portafolio_clave = ["portafolio","catalogo","servicios","productos"]

    # Delega el registro en la DB y la exportación a Google Sheets a un hilo
    threading.Thread(target=_agregar_mensajes_log_thread_safe, args=(json.dumps(log_data_in),)).start()

    if mensaje_procesado == "hola" or mensaje_procesado == "hi" or mensaje_procesado == "hello":
        user_language = "es"
        ESTADO_USUARIO = "nuevo"
        send_initial_messages(ESTADO_USUARIO,telefono_id, user_language)        
    #elif mensaje_procesado == "btn_si1" or mensaje_procesado in ["portafolio","servicios","productos"]:
    elif "btn_si1" in  mensaje_procesado or any (palabra in mensaje_procesado for palabra in portafolio_clave):
        #user_language = "es"
        user_language = obtener_idioma_usuario(telefono_id)   

        ESTADO_USUARIO = "interesado"
        request1_messages(ESTADO_USUARIO, telefono_id, user_language)  
    elif mensaje_procesado == "btn_no1" or mensaje_procesado == "no":
        #user_language = "es"
        user_language = obtener_idioma_usuario(telefono_id)  

        ESTADO_USUARIO = "no_interesado"
        chat_history = send_ia_prompt("prompt_ia_no", telefono_id,user_language)
        send_ia_message(ESTADO_USUARIO, telefono_id, mensaje_procesado, chat_history, user_language)
    elif mensaje_procesado in ["btn_1","btn_2","btn_3","btn_4","btn_5","btn_6","btn_7","btn_8","btn_9"]:
        #user_language = "es"
        user_language = obtener_idioma_usuario(telefono_id)  

        ESTADO_USUARIO = "interesado"
        chat_history = send_ia_prompt("prompt_ia_yes", telefono_id,user_language)
        send_ia_message(ESTADO_USUARIO, telefono_id, mensaje_procesado, chat_history, user_language)
    elif mensaje_procesado in ["btn_0" ,"asesor"]:
        #user_language = "es"
        user_language = obtener_idioma_usuario(telefono_id)  

        ESTADO_USUARIO = "quiere_asesor"
        send_adviser_messages(ESTADO_USUARIO,telefono_id, mensaje_procesado,  user_language)
    elif mensaje_procesado  in ["salir", "exit", "quit"]:
        #user_language = "es"
        user_language = obtener_idioma_usuario(telefono_id)  

        ESTADO_USUARIO = "calificado"
        chat_history = send_ia_prompt("prompt_ia_yes", telefono_id,user_language)
        send_ia_message(ESTADO_USUARIO, telefono_id, mensaje_procesado, chat_history, user_language)
    else:
        #user_language = "es"
        user_language = obtener_idioma_usuario(telefono_id)  

        #no se actualiza estado esperando que herede la ultma condición de: ESTADO_USUARIO
        ESTADO_USUARIO = "neutro"
        chat_history = send_ia_prompt("prompt_ia_yes", telefono_id,user_language)
        send_ia_message(ESTADO_USUARIO, telefono_id, mensaje_procesado, chat_history, user_language)



def send_initial_messages(ESTADO_USUARIO,telefono_id, lang):
    """Envía los mensajes iniciales (bienvenida, imagen, botones Si/No) después de seleccionar idioma."""
    # Saludo en el idioma elegido

    message_response = get_message(lang, "welcome_initial")
    send_message_and_log(lang,ESTADO_USUARIO, telefono_id, message_response, 'text')

    # Imagen
    message_response = get_message(lang, "greeting_text1") # Quizás 'greeting_image_caption' sea más apropiado aquí
    send_message_and_log(lang,ESTADO_USUARIO, telefono_id, message_response, 'image')

    #Botones pregunta1
    # Definimos los títulos de los botones según el idioma
    if lang == "es":
        si_title = "Si"
        no_title = "Tal vez"
    else:
        si_title = "Yes"
        no_title = "Maybe"
    
    # Definimos los IDs de los botones (estos no cambian con el idioma)
    si_id = "btn_si1"
    no_id = "btn_no1"

    message_response_for_buttons = get_message(lang, "greeting_text2")

    send_message_and_log(
        lang,
        ESTADO_USUARIO,
        telefono_id, 
        message_response_for_buttons, 
        'button', 
        button_titles=[si_title, no_title], # Pasamos los títulos que varían por idioma
        button_ids=[si_id, no_id]           # Pasamos los IDs fijos
    )


def request1_messages(ESTADO_USUARIO, telefono_id, lang):
    """El usuario esta interesado y desea conocer mas del tema"""
    #titulos

    message_response_for_list = get_message(lang, "portafolio")

    send_message_and_log(
        lang,
        ESTADO_USUARIO,
        telefono_id, 
        message_response_for_list, 
        'list', 
        list_titles = get_message(lang, "list_titles1"), # El titulo no debe superar 24 caracteres
        list_ids = ["btn_1","btn_2","btn_3","btn_4","btn_5","btn_6","btn_7","btn_8","btn_9","btn_0"],           # Pasamos los IDs fijos
        list_descrip= get_message(lang, "list_descrip1") # la descripcion  no debe superar 72 caracteres
    )

def send_adviser_messages(ESTADO_USUARIO, telefono_id,mensaje_procesado, lang):
    """El usuario esta interesado y quiere concretar una cita"""

    chat_history = send_ia_prompt("prompt_ia_yes", telefono_id,lang)
    send_ia_message(ESTADO_USUARIO,telefono_id, mensaje_procesado, chat_history, lang)


def send_message_and_log(lang,ESTADO_USUARIO,telefono_id, message_text, message_type='text', button_titles=None, button_ids=None, list_titles=None, list_ids=None, list_descrip=None):
    """
    Construye y envía un mensaje de WhatsApp, y registra la interacción.
    :param telefono_id: ID del teléfono del destinatario.
    :param message_text: Texto principal del mensaje.
    :param message_type: Tipo de mensaje ('text', 'image', 'button').
    :param button_titles: Lista de títulos para botones (solo para 'button' type).
    :param button_ids: Lista de IDs para botones (solo para 'button' type).
    """
    data = {}
    if message_type == 'text':
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono_id,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message_text
            }
        }
    elif message_type == 'image':
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono_id,
            "type": "image",
            "image": {
                "link": IMA_SALUDO_URL,
                "caption": message_text # El texto se usa como descripción de la imagen
            }
        }
    elif message_type == 'button' and button_titles and button_ids and len(button_titles) == len(button_ids):
        buttons = []
        for i in range(len(button_titles)):
            buttons.append({
                "type": "reply",
                "reply": {"id": button_ids[i], "title": button_titles[i]}
            })
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono_id,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": message_text},
                "footer": {"text": "Select one of the options:"},
                "action": {"buttons": buttons}
            }
        }
    
    elif message_type == 'list' and list_titles and list_ids and list_descrip and len(list_titles) == len(list_ids) and len(list_ids) == len(list_descrip):
        
        lista_sections = []
        
        for i in range(len(list_titles)):
            lista_sections.append(
                {
                    "id": list_ids[i], 
                    "title": list_titles[i], 
                    "description": list_descrip[i]
                }
            )

        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono_id,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": message_text},
                "footer": {"text": get_message(lang, "list_footer_text")},
                "action": {
                    "button": get_message(lang, "portafolio1"),
                    "sections": [
                        {
                            "title": "Servicios disponibles",
                            "rows": lista_sections
                        }
                    ]
                }
            }
        }

    else:
        logging.warning(f"Tipo de mensaje no soportado o parámetros incompletos: {message_type}")
        return # No procesar si el tipo es incorrecto o faltan parámetros

    # Registrar el mensaje de salida y enviarlo
    log_data_out = {
        'telefono_usuario_id': telefono_id,
        'plataforma': 'whatsapp 📞📱💬',
        'mensaje': message_text, # El texto del mensaje que se envía
        'estado_usuario': ESTADO_USUARIO,
        'etiqueta_campana': 'Respuesta Bot',
        'agente': AGENTE_BOT
    }
    #agregar_mensajes_log(json.dumps(log_data_out))
    #exportar_eventos()

    threading.Thread(target=_agregar_mensajes_log_thread_safe, args=(json.dumps(log_data_out),)).start()

    send_whatsapp_message(data)

# --- Ejecución del Programa ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)


    