#_______________________________________________________________________________________
"""
Dios bendiga este negocio y la properidad nos acompañe de la mano de Dios y su santo hijo AMEN
"""
#_______________________________________________________________________________________
#1. IMPORTS

from flask import Flask, request, json, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta #ayuda para el calculo de tiempo
import http.client
import logging
import os
from dotenv import load_dotenv
import openai
from prompt_ia import get_message
from io import StringIO # Importar StringIO para el manejo de credenciales
import threading
from threading import Lock
import psycopg2

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

Actualiza 21/07/2025:
-Configuracion token fijo y numero de telefono en meta

Actualiza 17/12/2025:
- Se actualiza persistencia de historial de conversacion de la IA en BD esto con el fin
de mejorar la persistencia cuando existen varios usuarios interactuando
- se cambian varibles globales por class ConversationManager

"""
#_______________________________________________________________________________________

# --- Recursos ---
IMA_SALUDO_URL = os.getenv("IMA_SALUDO_URL")
AGENTE_BOT = "Bot" # Usamos una constante para el agente
ESTADO_USUARIO = ""

#_______________________________________________________________________________________
#2. CONFIGURACIÓN DE LA APP

app = Flask(__name__)

# Configura el logger (Log de eventos para ajustado para utilizarlo en render)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuración de base de datos SQLITE
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

#_______________________________________________________________________________________
#3. MODELOS (Log, UsuariosBot, ConversationHistory)

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

class UsuariosBot(db.Model):
    id_bot = db.Column(db.Integer, primary_key=True)
    lang = db.Column(db.Text)
    telefono_usuario_id = db.Column(db.Text) #es el mismo whatsapp_id
    crm_contact_id = db.Column(db.Text)
    nombre_preferido = db.Column(db.Text)
    estado_usuario = db.Column(db.Text)
    fecha_y_hora = db.Column(db.DateTime, default=datetime.utcnow)

class ConversationHistory(db.Model):
    """Tabla para el historial de conversaciones con IA"""
    __tablename__ ='conversation_history'

    id = db.Column(db.Integer, primary_key=True)
    telefono_usuario_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    history = db.Column(db.JSON, nullable=False) 
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    #muestra el objeto en consola
    def __repr__(self):
        return f'<ConversationHistory: {self.telefono_usuario_id}>'

#_______________________________________________________________________________________
#4. CONVERSATIONMANAGER (Clase)
class ConversationManager:
    """Gestor de conversaciones con persistencia en BD"""

    def __init__(self):
        self.memory_cache = {}
        self.cache_lock = Lock()

    def get_history(self, telefono_id):
        """Obtiene historial desde BD con cache"""
        with self.cache_lock:
            #1. Revisa cache primero
            if telefono_id in self.memory_cache:
                logging.info(f"get_history: Hisotrial obtenido de cache para {telefono_id}")
                return self.memory_cache[telefono_id]
            
            #2. Si no esta en cache, consulta BD
            conversation = ConversationHistory.query.filter_by(
                telefono_usuario_id = telefono_id
            ).first()

            if conversation:
                history = conversation.history #invoca el campo history de la tabla
                logging.info(f"get_history: Historial obtenido de la BD para {telefono_id}")
            else:
                #3. Inicializar con prompt del sistema
                history = self._init_system_prompt(telefono_id)
                logging.info(f"get_history: Nuevo historial creado {telefono_id}")
            
            #4. Guarda cache
            self.memory_cache[telefono_id] = history
            return history
    
    def save_history(self, telefono_id, history):
        """Guarda historial en BD y actauliza cache"""
        with self.cache_lock:
            try:
                conversation = ConversationHistory.query.filter_by(
                    telefono_usuario_id = telefono_id
                ).first()

                if conversation:
                    conversation.history = history
                    conversation.updated_at = datetime.utcnow()
                else:
                    conversation = ConversationHistory(
                        telefono_usuario_id = telefono_id,
                        history = history
                    )
                    db.session.add(conversation)
                
                db.session.commit()
                self.memory_cache[telefono_id] = history
                logging.info(f"save_history: Historial guardado para {telefono_id}")
                    
            except Exception as e:
                db.session.rollback()
                logging.error(f"save_history: Error guardando historial para {telefono_id}: {e}")
                raise

    def _init_system_prompt(self, telefono_id, prompt):
        """Inicializa conversación con prompt del sistema"""
        try:
            message_prompt = get_message("en", prompt)
            logging.info(f"_init_system_prompt: incia con el prompt IA")
            return [{"role": "system", "content": message_prompt}]
        except Exception as e:
            logging.error(f"_init_system_prompt:Error inicializando prompt IA: {e}")
            return [{"role": "system", "content": message_prompt}]
        
    def clear_history(self, telefono_id):
        """Limpia historial de un suario especifico"""
        with self.cache_lock:
            try:
                conversation = ConversationHistory.query.filter_by(
                    telefono_usuario_id = telefono_id
                    ).first()
                
                if conversation:
                    db.session.delete(conversation)
                    db.session.commit()

                if telefono_id in self.memory_cache:
                    del self.memory_cache[telefono_id]

                logging.info(f"clear_history:Historial limpriado para {telefono_id}")
            except Exception as e:
                db.session.rollback()
                logging.error(f"clear_history: Error limpiando el historial para el {telefono_id}:{e}")

    def clear_old_histories(self, days=7):
        """Limpias historiales antiguos (se ejecuta manualmente)"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            old_conversations = ConversationHistory.query.filter_by(
                ConversationHistory.updated_at < cutoff_date
            ).all()

            count = 0
            for conversation in old_conversations:
                if conversation.telefono_usuario_id in self.memory_cache:
                    del self.memory_cache[conversation.telefono_usuario_id]

                db.session.delete(conversation)
                count+=1
            
            db.session.commit()
            logging.info(f"clear_old_histories: limpiados {count} historiales antiguos")
            return count

        except Exception as e:
            db.session.rollback()
            logging.error(f"clear_old_histories: Erro9r limpiando historiales antiguos: {e}")
            return 0
       
#_______________________________________________________________________________________
#5. INTANCIA GLOBAL DEL MANAGER

conversation_manager = ConversationManager()

#_______________________________________________________________________________________
#6. FUNCIONES DE IA

def send_ia_prompt(prompt, telefono_id):
    """Inicializa o actualiza el prompt del sistema, retorna el historial real desde el manager"""
    try:
        history = conversation_manager.get_history(telefono_id)

        if history and history[0]["role"] =="system":
            message_prompt = get_message("en", prompt)
            history[0]["content"] = message_prompt
            conversation_manager.save_history(telefono_id, history)

    except Exception as e:
        logging.error(f"send_ia_prompt: Error para {telefono_id}: {e}")


def send_ia_message(ESTADO_USUARIO, telefono_id, message_text, lang):
    """Gestiona la conversacion con la IA usando persistencia en  BD"""

    openai.api_key = os.environ.get("OPENAI_API_KEY")
    
    # 1. Solicitudes de portafolio en medio de la conversacion 
    if message_text.lower() in ["portfolio", "view services", "show options", "services",
                                  "portafolio", "ver servicios", "mostrar opciones", "servicios"]:
        request1_messages(telefono_id, lang)
        return

    try:
        # 2. Obtiene el hisotiral desde manager (cache + BD) 
        chat_history = conversation_manager.get_history(telefono_id)

        if not chat_history:
            logging.error(f"send_ia_message: No se puede obtener historial para {telefono_id}")
            return
        
        # 3. Agregar mensaje del usuario
        chat_history.append({"role": "user", "content": message_text})

        # 4. Limitar histortial para evitar exceder tokens
        MAX_MESSAGES = 20
        if len(chat_history) > MAX_MESSAGES + 1:
            chat_history = chat_history[0] + chat_history[-(MAX_MESSAGES):]

        # 5. Llamar a OPENIA
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini", #"gpt-3.5-turbo",
            messages=chat_history,
            temperature=0.7,
            max_tokens=500
        )

        # 6. Obtener la respuesta del asistente
        respuesta_bot = response['choices'][0]['message']['content']
        
        # 7. Agregar respuesta del bot al historial
        chat_history.append({"role": "assistant", "content": respuesta_bot})

        # 8. Guardar en BD
        conversation_manager.save_history(telefono_id, chat_history)

        # 9. guardar en el log y enviar mensaje
        send_message_and_log(ESTADO_USUARIO,telefono_id, respuesta_bot, 'text')

        logging.info(f"send_ia_message: Consulta a la IA {telefono_id}: {respuesta_bot[:100]}...")
    
    except openai.error.RateLimitError:
        logging.error(f"send_ia_message: Rate limit excedido para {telefono_id}")
        send_message_and_log(
            ESTADO_USUARIO, 
            telefono_id, 
            "Estamos experimentando alta demanda. Por favor intenta en unos momentos.", 
            'text'
        )
        
    except openai.error.InvalidRequestError as e:
        logging.error(f"send_ia_message: Request inválido para {telefono_id}: {e}")
        conversation_manager.clear_history(telefono_id)
        send_message_and_log(
            ESTADO_USUARIO, 
            telefono_id, 
            "He reiniciado nuestra conversación. ¿En qué puedo ayudarte?", 
            'text'
        )
        
    except Exception as e:
        logging.error(f"send_ia_message: Error en conversación con IA para {telefono_id}: {e}")
        send_message_and_log(
            ESTADO_USUARIO, 
            telefono_id, 
            "Lo siento, hubo un error procesando tu mensaje. Por favor intenta nuevamente.", 
            'text'
        )
#_______________________________________________________________________________________
#7. FUNCIONES DE LOG (threading)
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

"""
def agregar_mensajes_log(datos_json):
    Agrega un registro de mensaje a la base de datos.
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

"""
#_______________________________________________________________________________________
#8. API WHATSAPP
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
#_______________________________________________________________________________________
#9. ENDPOINTS
# --- Funciones de la Aplicación Flask ---
@app.route('/')
def index():
    """Renderiza la página principal con los registros del log."""
    registros = Log.query.all()
    registros_ordenados = sorted(registros, key=lambda x: x.fecha_y_hora, reverse=True)
    return render_template('index.html', registros=registros_ordenados)



""""Función para cargar o actualizar prompt de la IA, y mantener el hilo de
conversación con un usuario"""

"""
user_histories = {}

def send_ia_prompt(prompt,telefono_id):
    try:
        openai.api_key = os.environ.get("OPENAI_API_KEY")
        message_prompt = get_message("en", prompt)

        if telefono_id not in user_histories:
            user_histories[telefono_id] = [{"role": "system", "content": message_prompt}]
        
        logging.info(f"Consulta a la IA: {user_histories}")
    except Exception as e:
        logging.error(f"Error con la IA: {e}")

    return list(user_histories[telefono_id])
"""
"""Función que mantenie el flujo de la conversación de la IA"""
"""
def send_ia_message(ESTADO_USUARIO, telefono_id, message_text, chat_history_prompt, lang):
    openai.api_key = os.environ.get("OPENAI_API_KEY")
    
    # 1. Si el usuario solicita ver el portafolio
    #if message_text in ["portafolio", "ver servicios", "mostrar opciones", "servicios"]:
    if message_text in ["Portfolio","View Services","Show Options","Services"]:
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
            model="gpt-4o-mini", #"gpt-3.5-turbo",
            messages=chat_history
        )

        # Obtener la respuesta del asistente
        respuesta_bot = response['choices'][0]['message']['content']
        #print(f"Asistente: {respuesta_bot}\n")

        # Agregar respuesta del bot al historial
        chat_history.append({"role": "assistant", "content": respuesta_bot})

        send_message_and_log(ESTADO_USUARIO,telefono_id, respuesta_bot, 'text')

        logging.info(f"Consulta a la IA: {respuesta_bot}")
    except Exception as e:
        logging.error(f"Error con la IA: {e}")
        """

@app.route('/clear_history/<telefono_id>', methods=['POST'])
def clear_user_history(telefono_id):
    """Endpoint para limpiar historial de un usuario"""
    try:
        conversation_manager.clear_history(telefono_id)
        return jsonify({
            "status": "success", 
            "message": f"Historial limpiado para {telefono_id}"
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/cleanup_old_histories', methods=['POST'])
def cleanup_old_histories_endpoint():
    """
    Endpoint para limpiar historiales antiguos manualmente o con cron job
    Uso: POST /cleanup_old_histories?days=7
    """
    try:
        days = int(request.args.get('days', 7))
        count = conversation_manager.clear_old_histories(days)
        return jsonify({
            "status": "success",
            "message": f"Limpiados {count} historiales antiguos (>{days} días)"
        }), 200
    except Exception as e:
        logging.error(f"Error en cleanup endpoint: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
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
        'etiqueta_campana': 'usuarios nuevos',
        'agente': AGENTE_BOT
    }

    saludo_clave = ["hola","hi","hello","start","alo"]
    portafolio_clave = ["portafolio","catálogo","servicios","productos"]

    # Delega el registro en la DB y la exportación a Google Sheets a un hilo
    threading.Thread(target=_agregar_mensajes_log_thread_safe, args=(json.dumps(log_data_in),)).start()

    #if mensaje_procesado == "hola" or mensaje_procesado == "hi" or mensaje_procesado == "hello":
    if "hola" in mensaje_procesado  or any(palabra in mensaje_procesado for palabra in saludo_clave):
        user_language = "en"
        ESTADO_USUARIO = "nuevo"
        send_initial_messages(ESTADO_USUARIO,telefono_id, user_language)        
    #elif mensaje_procesado == "btn_si1" or mensaje_procesado in ["portafolio","servicios","productos"]:
    elif "btn_si1" in  mensaje_procesado or any (palabra in mensaje_procesado for palabra in portafolio_clave):
        user_language = "en"
        ESTADO_USUARIO = "interesado"
        request1_messages(ESTADO_USUARIO, telefono_id, user_language)  
    elif mensaje_procesado == "btn_no1" or mensaje_procesado == "no":
        user_language = "en"
        ESTADO_USUARIO = "no_interesado"
        chat_history = send_ia_prompt("prompt_ia_no", telefono_id)
        send_ia_message(ESTADO_USUARIO, telefono_id, mensaje_procesado, chat_history, user_language)
    elif mensaje_procesado in ["btn_1","btn_2","btn_3","btn_4","btn_5","btn_6","btn_7","btn_8","btn_9"]:
        user_language = "en"
        ESTADO_USUARIO = "interesado"
        chat_history = send_ia_prompt("prompt_ia_yes", telefono_id)
        send_ia_message(ESTADO_USUARIO, telefono_id, mensaje_procesado, chat_history, user_language)
    elif mensaje_procesado in ["btn_0" ,"asesor"]:
        user_language = "en"
        ESTADO_USUARIO = "quiere_asesor"
        send_adviser_messages(ESTADO_USUARIO,telefono_id, mensaje_procesado,  user_language)
    elif mensaje_procesado  in ["salir", "exit", "quit"]:
        user_language = "en"
        ESTADO_USUARIO = "calificado"
        chat_history = send_ia_prompt("prompt_ia_yes", telefono_id)
        send_ia_message(ESTADO_USUARIO, telefono_id, mensaje_procesado, chat_history, user_language)
    else:
        user_language = "en"
        #no se actualiza estado esperando que herede la ultma condición de: ESTADO_USUARIO
        ESTADO_USUARIO = "neutro"
        chat_history = send_ia_prompt("prompt_ia_yes", telefono_id)
        send_ia_message(ESTADO_USUARIO, telefono_id, mensaje_procesado, chat_history, user_language)



def send_initial_messages(ESTADO_USUARIO,telefono_id, lang):
    """Envía los mensajes iniciales (bienvenida, imagen, botones Si/No) después de seleccionar idioma."""
    # Saludo en el idioma elegido

    message_response = get_message(lang, "welcome_initial")
    send_message_and_log(ESTADO_USUARIO, telefono_id, message_response, 'text')

    # Imagen
    message_response = get_message(lang, "greeting_text1") # Quizás 'greeting_image_caption' sea más apropiado aquí
    send_message_and_log(ESTADO_USUARIO, telefono_id, message_response, 'image')

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
        ESTADO_USUARIO,
        telefono_id, 
        message_response_for_list, 
        'list', 
        list_titles = ["📱DDA & Mobile Campaigns","📊Display Media Planning","🛒Ecommerce Strategy",
                       "📣Paid Social Media","🎯Audience Studies","🚀Digital Marketing",
                       "📰Media Strategy","🤖Custom Bot Development","🌐WebSites",
                       "🗣️Talk to an Agent"], # El titulo no debe superar 24 caracteres
        list_ids = ["btn_1","btn_2","btn_3","btn_4","btn_5","btn_6","btn_7","btn_8","btn_9","btn_0"],           # Pasamos los IDs fijos
        list_descrip=["Physical & Mobile Convert.",
                      "Formats and Creatives",
                      "Leading Strategies",
                      "Paid Social Media Mgmt",
                      "Analysis and Trends",
                      "SEO, Social Media & PPC",
                      "Best Media Strategy",
                      "Chatbots & Automation",
                      "Web Dev and UX",
                      "Expert Human Assistance"] # la descripcion  no debe superar 72 caracteres
    )


def send_adviser_messages(ESTADO_USUARIO, telefono_id,mensaje_procesado, lang):
    """El usuario esta interesado y quiere concretar una cita"""

    #message_response = get_message(lang, "agent")
    #send_message_and_log(ESTADO_USUARIO, telefono_id, message_response, 'text')
    chat_history = send_ia_prompt("prompt_ia_yes", telefono_id)
    send_ia_message(ESTADO_USUARIO,telefono_id, mensaje_procesado, chat_history, lang)


def send_message_and_log(ESTADO_USUARIO,telefono_id, message_text, message_type='text', button_titles=None, button_ids=None, list_titles=None, list_ids=None, list_descrip=None):
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
                "footer": {"text": get_message("en", "list_footer_text")},
                "action": {
                    "button": "Portfolio",
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

#_______________________________________________________________________________________
#10. INICIALIZACIÓN
# Crear tabla si no existe
with app.app_context():
    db.create_all()
    logging.info(f"Tablas inicializadas: Log, UsuariosBot, ConversationHistory")
#_______________________________________________________________________________________
# --- Ejecución del Programa ---

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)
#_______________________________________________________________________________________

    