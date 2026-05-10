#_______________________________________________________________________________________
"""
Dios bendiga este negocio y la properidad nos acompañe de la mano de Dios y su santo hijo AMEN
"""
#_______________________________________________________________________________________
#1. IMPORTS
from flask import debughelpers
from asyncio import exceptions
from asyncio import exceptions
from flask import Flask, request, json, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta #ayuda para el calculo de tiempo
import http.client
import logging, requests
import os
from dotenv import load_dotenv
import openai
from prompt_ia import get_message
from io import StringIO # Importar StringIO para el manejo de credenciales
import threading
from threading import Lock

load_dotenv()
#_______________________________________________________________________________________
"""
Version 1.1:
Creación 04/2025:

Descripción: Primer Bot de Whatsapp para la empresa TicAll Media, 
integrado con IA, un solo  idioma integrado con Zoho Sales IQ

Caracteristicas: 

- AI gpt-3.5-turbo inicialmente, en python con openai==0.28.1
- En gitgnore, se agrega el archivo .env
- Las credenciales se suben en render directamente

Version 1.2:
- Se agrega conexion a app B (API_middleware_zoho), la cual es un puente 
entre App A de Waba y Zoho Sales IQ
- La Función send_whatsapp_from_middleware permite la recepción de los
mensajes de Zoho y la interaccion del agente humano

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

Version 3.3

Actualiza 17/12/2025:
- Se actualiza persistencia de historial de conversacion de la IA en BD esto con el fin
de mejorar la persistencia cuando existen varios usuarios interactuando
- se cambian varibles globales por class ConversationManager

Version 4.0:
Actualiza 08/01/2026:
- Adecuación producción en Version 4.0 beta
- Fusión codigo App de Produccion, con Version 1.2 Beta que tiene conexion a Zoho

Version 4.1:
Actualiza 09/05/2026:
- Soporte para recepcion de archivos e imagenes desde Zoho SalesIQ (App B)
- Ajuste en send_whatsapp_from_middleware para detectar media_url y media_type
- Ajuste en send_message_and_log para enviar documentos e imagenes dinamicas por WhatsApp
- Correccion de bloque 'image' duplicado en send_message_and_log
- Agregado prefijo visual ═════════════ 🤖 TAM Bot ═════════════ a mensajes del bot enviados a Zoho para diferenciacion del operador
- Sistema de modo operador: pausa la IA cuando un agente humano responde desde Zoho (30 min)
- Logging detallado en /api/envio_whatsapp para diagnostico de envio desde Zoho

"""
#_______________________________________________________________________________________
# --- Recursos ---
AGENTE_BOT = "Bot" # Usamos una constante para el agente
IMA_SALUDO_URL = os.getenv("IMA_SALUDO_URL")
APP_B_URL = os.getenv("APP_B_URL")

# --- Modo Operador: desconecta IA cuando agente humano toma control ---
MODO_OPERADOR = {}
MODO_OPERADOR_LOCK = Lock()
TIEMPO_PAUSA_MINUTOS = 30

def activar_modo_operador(telefono_id):
    """Marca un número como en modo operador (IA pausada)."""
    with MODO_OPERADOR_LOCK:
        MODO_OPERADOR[telefono_id] = datetime.now()
        logging.info(f"activar_modo_operador: [MODO OPERADOR] Activado para {telefono_id}")

def desactivar_modo_operador(telefono_id):
    """Reactiva el bot para un número."""
    with MODO_OPERADOR_LOCK:
        MODO_OPERADOR.pop(telefono_id, None)
        logging.info(f"activar_modo_operador: [MODO OPERADOR] Desactivado para {telefono_id}")

def esta_en_modo_operador(telefono_id):
    """Verifica si un número está en modo operador (últimos N minutos)."""
    with MODO_OPERADOR_LOCK:
        if telefono_id in MODO_OPERADOR:
            tiempo_pasado = datetime.now() - MODO_OPERADOR[telefono_id]
            if tiempo_pasado < timedelta(minutes=TIEMPO_PAUSA_MINUTOS):
                return True
            else:
                del MODO_OPERADOR[telefono_id]
        return False

#_______________________________________________________________________________________
#2. CONFIGURACIÓN DE LA APP
# --- Funciones de la Aplicación Flask ---
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
    """Tabla de estados del Usuario y su interaccion con el Bot"""
    __tablename__ ='usuarios_bot'

    telefono_usuario_id = db.Column(db.String(50), primary_key=True)
    fecha_y_hora = db.Column(db.DateTime, default=datetime.utcnow)
    chat_finalizado = db.Column(db.Boolean, default=False)
    agente_actual = db.Column(db.String(50), default="IA") #estados IA y Asesor

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

    def get_history(self, telefono_id, lang ="en", prompt_type="prompt_ia_yes"):
        """
            Obtiene historial desde BD con cache
            Si no existe, lo inicializa automáticamente con el prompt del sistema.
        """
        with self.cache_lock:
            #1. Revisa cache primero
            if telefono_id in self.memory_cache:
                logging.info(f"get_history: Historial obtenido de cache para {telefono_id}")
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
                history = self._init_system_prompt(telefono_id, lang, prompt_type)
                logging.info(f"get_history: Nuevo historial creado {telefono_id} - lang: {lang}, Tipo: {prompt_type}")
            
            #4. Guarda cache
            self.memory_cache[telefono_id] = history
            return history
    
    def save_history(self, telefono_id, history):
        """Guarda historial en BD y actualiza cache"""
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

    def _init_system_prompt(self, telefono_id, lang ="en", prompt_type="prompt_ia_yes"):
        """Inicializa conversación con prompt del sistema"""
        try:
            message_prompt = get_message(lang, prompt_type)
            logging.info(f"_init_system_prompt: incia con el prompt IA")
            return [{"role": "system", "content": message_prompt}]
        
        except Exception as e:
            logging.error(f"_init_system_prompt: Error inicializando prompt IA: {telefono_id}: {e}")
            return [{"role": "system", "content": message_prompt}]

    def update_system_prompt(self, telefono_id, lang ="en", prompt_type="prompt_ia_yes"):
        """
        Actualiza el prompt del sistema para un usuario existente.
        Útil cuando quieres cambiar entre prompt_ia_yes y prompt_ia_no.
        
        Args:
            telefono_id: ID del teléfono del usuario
            lang: Idioma ("es" o "en")
            prompt_type: Tipo de prompt ("prompt_ia_yes" o "prompt_ia_no")
        """
        with self.cache_lock:
            try:
                history = self.get_history(telefono_id, lang, prompt_type)
                
                # Actualizar el primer mensaje (system prompt)
                if history and history[0]["role"] == "system":
                    # Cargar nuevo prompt desde prompt_ia.py
                    message_prompt = get_message(lang, prompt_type)
                    history[0]["content"] = message_prompt
                    self.save_history(telefono_id, history)
                    logging.info(f"Prompt actualizado para {telefono_id} - Lang: {lang}, Tipo: {prompt_type}")
                    return True
                return False
                
            except Exception as e:
                logging.error(f"Error actualizando prompt para {telefono_id}: {e}")
                return False
                
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

def send_ia_message(ESTADO_USUARIO, telefono_id, message_text, lang ="en", prompt_type="prompt_ia_yes"):
    """Gestiona la conversacion con la IA usando persistencia en  BD"""

    openai.api_key = os.environ.get("OPENAI_API_KEY")
    
    # 1. Solicitudes de portafolio en medio de la conversacion 
    if message_text.lower() in ["portfolio", "view services", "show options",
                                  "portafolio", "ver servicios", "mostrar opciones"]:
        request1_messages(telefono_id, lang)
        return

    try:
        # 2. Obtiene el hisotiral desde manager (cache + BD) 
        #Obtener historial (se inicializa automáticamente si es la primera vez)
        chat_history = conversation_manager.get_history(telefono_id, lang, prompt_type)

        if not chat_history:
            logging.error(f"send_ia_message: No se puede obtener historial para {telefono_id}")
            return
        
        # 3. Agregar mensaje del usuario
        chat_history.append({"role": "user", "content": message_text})

        # 4. Limitar histortial para evitar exceder tokens
        MAX_MESSAGES = 30
        if len(chat_history) > MAX_MESSAGES + 1:
            chat_history = [chat_history[0]] + chat_history[-(MAX_MESSAGES):]

        """
        if len(chat_history) > MAX_MESSAGES + 1:
            chat_history = [chat_history[0]] + chat_history[1:6] + chat_history[-(MAX_MESSAGES-5):]
            logging.info(f"send_ia_message: Historial recortado para {telefono_id} - {len(chat_history)} mensajes")
        """
        # 5. Llamar a OPENIA
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo", #"gpt-4o-mini"
            messages=chat_history,
            temperature=0.7,
            max_tokens=500
        )
        
        """
        # 5. CRÍTICO: Calcular tokens y ajustar max_tokens dinámicamente
        chars_per_token = 4 if lang == "es" else 5
        total_chars = sum(len(str(msg.get('content', ''))) for msg in chat_history)
        estimated_input_tokens = total_chars // chars_per_token
        
        # Ajustar tokens de salida según contexto
        if estimated_input_tokens > 3000:
            max_output_tokens = 800
        elif estimated_input_tokens > 1500:
            max_output_tokens = 600
        else:
            max_output_tokens = 500
        
        logging.info(f"send_ia_message: Tokens estimados entrada={estimated_input_tokens}, max_salida={max_output_tokens}")

        # 6. Configuración optimizada para GPT-4o-mini
        
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=chat_history,
            temperature=0.7,
            max_tokens=max_output_tokens, #Dinamico segun contexto
            top_p=0.9, #ayuda a mantener la coherencia
            frequency_penalty=0.3, #reduce repeticiones
            presence_penalty=0.3 #fomenta variedad
        )
        respuesta_bot = response['choices'][0]['message']['content']
        chat_history.pop()
        chat_history.pop()
        """

        """
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini", #"gpt-3.5-turbo",
            messages=chat_history,
            temperature=0.7,
            max_tokens=max_output_tokens
        )
        """

        # 6. Obtener la respuesta del asistente
        respuesta_bot = response['choices'][0]['message']['content']
        
        # 7. Agregar respuesta del bot al historial
        chat_history.append({"role": "assistant", "content": respuesta_bot})

        # 8. Guardar en BD
        conversation_manager.save_history(telefono_id, chat_history)

        # 9. guardar en el log y enviar mensaje

            

        if "Tu información está completa" in respuesta_bot:
            """
            Se marca en la BD Usuariosbot que la conversación terminó y el agente actual es IA
            """
            #9.1 actualizando BD
            logging.info(f"send_ia_message: APAGADO DE BOT send_ia_message")

            usuario = UsuariosBot.query.filter_by(telefono_usuario_id =telefono_id).first()
            if usuario:
                usuario.chat_finalizado = True
                db.session.commit()
            

            #9.2 Se envia mensaje de confirmacion, es decir el resumen de los datos recopilados 
            send_message_and_log(
                ESTADO_USUARIO,
                telefono_id,
                respuesta_bot,
                'text',
                AGENTE_BOT = "Bot"
            )

            #Envia los botones de opciones finalizar-asesor
            send_message_and_log(
                ESTADO_USUARIO,
                telefono_id,
                '¿deseas continuar?',
                'button',
                button_titles = ["Hablar con un asesor","Finalizar"],
                button_ids = ["btn_asesor", "btn_finalizar"],
                AGENTE_BOT = "Bot"
            )
        else:
            send_message_and_log(
                ESTADO_USUARIO,
                telefono_id, 
                respuesta_bot, 
                'text',
                AGENTE_BOT = "Bot"
                )

        logging.info(f"send_ia_message: Consulta a la IA {telefono_id}: {respuesta_bot[:100]}...")
    
    except openai.error.RateLimitError:
        logging.error(f"send_ia_message: Rate limit excedido para {telefono_id}")
        send_message_and_log(
            ESTADO_USUARIO, 
            telefono_id, 
            "Estamos experimentando alta demanda. Por favor intenta en unos momentos.", 
            'text',
            AGENTE_BOT = "Bot"
            )
        
    except openai.error.InvalidRequestError as e:
        logging.error(f"send_ia_message: Request inválido para {telefono_id}: {e}")
        conversation_manager.clear_history(telefono_id)
        send_message_and_log(
            ESTADO_USUARIO, 
            telefono_id, 
            "He reiniciado nuestra conversación. ¿En qué puedo ayudarte?", 
            'text',
            AGENTE_BOT = "Bot"
            )
        
    except Exception as e:
        logging.error(f"send_ia_message: Error en conversación con IA para {telefono_id}: {e}")
        send_message_and_log(
            ESTADO_USUARIO, 
            telefono_id, 
            "Lo siento, hubo un error procesando tu mensaje. Por favor intenta nuevamente.", 
            'text',
            AGENTE_BOT = "Bot"
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
            logging.info(f"_agregar_mensajes_log_thread_safe:Registro de log añadido a DB (hilo): {datos.get('mensaje')}")
        except Exception as e:
            db.session.rollback() # Si hay un error, revertir la transacción
            logging.error(f"_agregar_mensajes_log_thread_safe:Error añadiendo log a DB (hilo): {e}")

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
@app.route('/')
def index():
    """Renderiza la página principal con los registros del log."""
    registros = Log.query.all()
    registros_ordenados = sorted(registros, key=lambda x: x.fecha_y_hora, reverse=True)
    return render_template('index.html', registros=registros_ordenados)

@app.route('/historyia')
def history_temp():
    """Muestra el historial temporal de las interesacciones con la IA"""
    registros_ia = ConversationHistory.query.all()
    registros_ia_ordenados = sorted(registros_ia, key=lambda x: x.created_at, reverse=True)
    return render_template('history_temp.html', registros_ia= registros_ia_ordenados )

@app.route('/clear_history/<telefono_id>', methods=['GET','POST'])
def clear_user_history(telefono_id):
    """Endpoint para limpiar historial de un usuario"""
    try:
        conversation_manager.clear_history(telefono_id)

        if request.method == 'GET':
            return render_template(
                'erase_history.html', 
                telefono_id = telefono_id, 
                mensaje ='El Historial de conversacion ha sido eliminado exitosamente, para: ' 
                ), 200
        
        # Si es POST (API), retornar JSON
        return jsonify({
            "status": "success", 
            "message": f"Historial limpiado para {telefono_id}"
        }), 200
    except Exception as e:

        if request.method == 'GET':
            return render_template(
                'erase_history.html', 
                telefono_id = telefono_id, 
                mensaje ='No se pudo limpiar el historial: ' 
                ), 500
        
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



@app.route('/api/envio_whatsapp', methods=['POST'])
def send_whatsapp_from_middleware():
    """
    Recibe una petición de la App B (middleware) y envía el mensaje a WhatsApp.
    """
    try:
        data = request.json
        logging.info(f"[ENVIO_WHATSAPP] Payload recibido de App B: {json.dumps(data)}")

        telefono_id = data.get("phone_number")
        message_text = data.get("message")
        sender_role = data.get("human_agent")
        media_url   = data.get("media_url")
        media_type  = data.get("media_type")

        logging.info(f"[ENVIO_WHATSAPP] phone_number={telefono_id}, sender_role={sender_role}, text={message_text}, media_url={media_url}")

        if not telefono_id or (not message_text and not media_url):
            logging.error(f"[ENVIO_WHATSAPP] Petición incompleta: phone_number={telefono_id}, text={message_text}, media_url={media_url}")
            return {f"status":"error","message":"Faltan phone_number o contenido"}, 400
        
        # Si viene de un agente humano, activar modo operador para evitar que la IA intervenga
        if sender_role == "human_agent":
            activar_modo_operador(telefono_id)
            logging.info(f"[ENVIO_WHATSAPP] Modo operador activado para {telefono_id} (mensaje de agente humano)")

        # Llama a tu función existente para enviar el mensaje
        #send_whatsapp_message(whatsapp_payload)
        ESTADO_USUARIO="Estado Zoho"

        msg_type = 'text'
        if media_url:
            msg_type = 'image' if 'image' in (media_type or '') else 'document'
        
        send_message_and_log(
            ESTADO_USUARIO, telefono_id, message_text or '', msg_type,
            media_url=media_url, AGENTE_BOT="Agente Humano"
        )
        
        return {"status": "ok", "message": "Mensaje enviado a WhatsApp"}, 200

    except Exception as e:
        logging.error(f"Error en /api/envio_whatsapp: {e}")
        return {"status": "error", "message": "Error interno del servidor"}, 500

#_______________________________________________________________________________________

"""
def agregar_mensajes_log(datos_json):
    #Agrega un registro de mensaje a la base de datos.
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

#___________________________________________________________________________
#___________________________________________________________________________
"""
Analiza el payload de la API de whatsapp y extrae el texto principal,
este solo se utili para extraer el mensaje generado por el bot
"""
def extraer_texto_para_zoho(data):
    try:
        message_type = data.get("type")
        texto_extraido = ""

        if message_type == 'text':
            texto_extraido = data.get('text',{}).get('body','')
        
        elif message_type == "image":
            texto_extraido = data.get('image',{}).get('caption','[Imagen enviada]')
        
        elif message_type == "document":
            texto_extraido = data.get('document',{}).get('caption','[Documento enviado]')

        elif message_type == "interactive":
            interactive_type = data.get('interactive',{}).get('type')

            if interactive_type in ['button','list']:
                texto_extraido = data.get('interactive',{}).get('body',{}).get('text','')
        
        #si no se encontro texto, devolver un placeholder para saber que se envio algo
        if not texto_extraido:
            return "[Mensjase interactivo o multimedia]"

        return texto_extraido

    except Exception as e:
        logging.error(f"extraer_texto_para_zoho: error extrayendo texto para zoho: {e}")
        return "[Error al procesar el mensaje para el bot]"

"""
Esta funcion registra primero en zoho y luego envia a whatsapp
"""
def enviar_respuesta_y_registrar_en_zoho(telefono_id, data, AGENTE_BOT):
    #1. Extrae el mensaje de humanos para zoho
    mensaje_para_zoho = extraer_texto_para_zoho(data)

    #2. Envia a zoho con una etiqueta para identificar los mensajes del bot
    if "Agente Humano" in AGENTE_BOT: #se agrega if para impedir que se reescriba informacion en zoho cuando habla el agente humano
        logging.info(f"Mensaje de (ECO) ignorado...") 
        
    elif mensaje_para_zoho:
        # Agregar prefijo para distinguir mensajes del bot en Zoho
        if AGENTE_BOT == "Bot":
            mensaje_para_zoho = f"═════════════ 🤖 TAM Bot ═════════════\n{mensaje_para_zoho}"
        logging.info(f"enviar_respuesta_y_registrar_en_zoho: '{mensaje_para_zoho}'")
        send_zoho(telefono_id, mensaje_para_zoho, "respuesta_bot")
    
    #3. Envia mensaje del bot a whatsapp
    send_whatsapp_message(data)

"""
envio de mensajes a Zoho Sales IQ
"""

def send_zoho(telefono_id, mensaje_texto, tag):
    payload = {
            "message": mensaje_texto,
            "user_id": telefono_id,
            "tag": tag  # 👈 nuevo campo opcional
        }

    try:
        resp = requests.post(APP_B_URL, json=payload, timeout=5)
        logging.info(f"✅ Reenviado a App B: {resp.status_code} {resp.text}")
    except Exception as e:
        logging.error(f"❌ Error reenviando a App B: {e}")  


#_______________________________________________________________________________________
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


        #comprobacion: si el payload contiene 'statuses' y no 'messages'
        #significa que es una notificacion de  (entregado, leido etc), de los mensajes enviados
        #se agrega para evitar el ECO de zoho

        if "statuses" in value:
            logging.info("webhook de estado de mensaje (ECO) recibido. Ingorado...")
            return "OK", 200


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

                #chat_history = [{"role": "system", "content": mensaje_texto}]
                AGENTE_BOT = "Usuario"
                #___________________________________________________________________________
                ##envio a Zoho Sales IQ

                send_zoho(telefono_id, mensaje_texto, "soporte_urgente" )

                #Actualizando UsuariosBot
                try:
                    #verificar UsuariosBot
                    visitor_db = db.session.get(UsuariosBot,telefono_id)
                    if visitor_db:
                        chat_estado = visitor_db.chat_finalizado
                        logging.info(f"recibir_mensajes: Estado de CHAT IA: {chat_estado}")
                    else:
                        nuevo_visitante = UsuariosBot(telefono_usuario_id=telefono_id, chat_finalizado=False, agente_actual="IA")
                        db.session.add(nuevo_visitante)
                        db.session.commit()
                        logging.info(f"recibir_mensajes: usuario ingresado en UsuariosBot: {telefono_id}")
                except Exception as e:
                    logging.error(f"recibir_mensajes: Error con DB: {e}")
                    db.session.rollback()


                #___________________________________________________________________________

                if esta_en_modo_operador(telefono_id):
                    logging.info(f"[MODO OPERADOR] IA pausada para {telefono_id}. Mensaje solo reenviado a Zoho.")
                else:
                    procesar_y_responder_mensaje(telefono_id, mensaje_texto, AGENTE_BOT)
            else:
                logging.info("Mensaje no procesable (sin ID de teléfono o texto de mensaje).")
        
        return jsonify({'message': 'EVENT_RECEIVED'}), 200
    except Exception as e:
        logging.error(f"Error en recibir_mensajes: {e}")
        return jsonify({'message': 'EVENT_RECEIVED_ERROR'}), 500

def procesar_y_responder_mensaje(telefono_id, mensaje_recibido, AGENTE_BOT):
    """
    Procesa un mensaje recibido, determina el idioma del usuario y envía la respuesta adecuada.
    Registra el mensaje entrante y la respuesta en la base de datos y Google Sheets.
    """
    mensaje_procesado = mensaje_recibido.lower()
    lang = ""
    
    # Primero, registra el mensaje entrante
    log_data_in = {
        'telefono_usuario_id': telefono_id,
        'plataforma': 'whatsapp 📞📱💬',
        'mensaje': mensaje_recibido,
        'estado_usuario': 'recibido',
        'etiqueta_campana': 'Interesado',
        'agente': AGENTE_BOT
    }

    saludo_clave = ["hola","hi","hello","start","alo"]
    portafolio_clave = ["portfolio", "view services", "show options",
                        "portafolio", "ver servicios", "mostrar opciones"]
    # Delega el registro en la DB y la exportación a Google Sheets a un hilo
    threading.Thread(target=_agregar_mensajes_log_thread_safe, args=(json.dumps(log_data_in),)).start()

    if "hola" in mensaje_procesado  or any(palabra in mensaje_procesado for palabra in saludo_clave):
        lang = "es"
        ESTADO_USUARIO = "nuevo"
        send_initial_messages(ESTADO_USUARIO, telefono_id, lang)        
    elif "btn_si1" in  mensaje_procesado or any (palabra in mensaje_procesado for palabra in portafolio_clave):
        lang = "es"
        ESTADO_USUARIO = "interesado"
        request1_messages(ESTADO_USUARIO, telefono_id, lang)  
    elif mensaje_procesado == "btn_no1" or mensaje_procesado == "no":
        lang = "es"
        prompt_type  = "prompt_ia_no"

        send_ia_message(
            ESTADO_USUARIO="no_interesado",
            telefono_id=telefono_id,
            message_text=mensaje_procesado,
            lang=lang,
            prompt_type=prompt_type
            )

    elif mensaje_procesado in ["btn_1","btn_2","btn_3","btn_4","btn_5","btn_6"]:
        lang = "es"
        prompt_type  = "prompt_ia_yes"

        send_ia_message(
            ESTADO_USUARIO="interesado",
            telefono_id=telefono_id,
            message_text=mensaje_procesado,
            lang=lang,
            prompt_type=prompt_type
            )
    #_____________________________________
    ##REVISAR LA FINALIZACION DEL CHAT
    #_____________________________________

    elif mensaje_procesado  in ["salir", "exit", "quit"]:
        lang = "es"
        prompt_type  = "prompt_ia_yes"

        send_ia_message(
            ESTADO_USUARIO="calificado",
            telefono_id=telefono_id,
            message_text=mensaje_procesado,
            lang=lang,
            prompt_type=prompt_type
            )
    #_____________________________________
    ##REVISAR CONECTAR ASESOR Y FINALIZACION
    #_____________________________________

    elif mensaje_procesado == "btn_asesor":
        lang = "es"
        prompt_type  = "prompt_ia_yes"

        #1. Actualizar estado del usuario a conectado
        usuario = UsuariosBot.query.filter_by(telefono_usuario_id = telefono_id).first()
        if usuario:
            usuario.agente_actual = "Asesor"
            db.session.commit()

        #2. Activar modo operador
        activar_modo_operador(telefono_id)
        
        send_ia_message(
            ESTADO_USUARIO="interesado",
            telefono_id=telefono_id,
            message_text=mensaje_procesado,
            lang=lang,
            prompt_type=prompt_type
            )

    elif mensaje_procesado == "btn_finalizar":
        lang = "es"
        prompt_type  = "prompt_ia_yes"

        send_ia_message(
            ESTADO_USUARIO="calificado",
            telefono_id=telefono_id,
            message_text=mensaje_procesado,
            lang=lang,
            prompt_type=prompt_type
            )

    else:
        lang = "es"
        prompt_type  = "prompt_ia_yes"

        send_ia_message(
            ESTADO_USUARIO="neutro",
            telefono_id=telefono_id,
            message_text=mensaje_procesado,
            lang=lang,
            prompt_type=prompt_type
            )



def send_initial_messages(ESTADO_USUARIO, telefono_id, lang):
    """Envía los mensajes iniciales (bienvenida, imagen, botones Si/No) después de seleccionar idioma."""
    # Saludo en el idioma elegido
    message_response = get_message(lang, "welcome_initial")
    send_message_and_log(ESTADO_USUARIO, telefono_id, message_response, 'text', AGENTE_BOT = "Bot")

    # Imagen
    message_response = get_message(lang, "greeting_text1") # Quizás 'greeting_image_caption' sea más apropiado aquí
    send_message_and_log(ESTADO_USUARIO, telefono_id, message_response, 'image', AGENTE_BOT = "Bot")

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
        button_ids=[si_id, no_id] ,# Pasamos los IDs fijos
        AGENTE_BOT = "Bot"
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
        list_titles = ["🔄TicAll Flow®️Ecosys","🤖Custom AI Agents","🛒Ecommerce Arch",
                       "⚡Performance Arch","📈Demand Generation","🌐High-Performance Webs"], # El titulo no debe superar 24 caracteres
        list_ids = ["btn_1","btn_2","btn_3","btn_4","btn_5","btn_6"],           # Pasamos los IDs fijos
        list_descrip=["Growth Infrastructure Design",
                      "AI Agents & Automation",
                      "Scalable Commerce Hubs",
                      "ROI-Driven Architecture",
                      "Scalable Paid Media",
                      "Scalable Web Systems"] ,# la descripcion  no debe superar 72 caracteres
        AGENTE_BOT = "Bot"
    )

def send_adviser_messages(ESTADO_USUARIO, telefono_id, mensaje_procesado, lang):
    """El usuario esta interesado y quiere concretar una cita"""
    #message_response = get_message(lang, "agent")
    #send_message_and_log(telefono_id, message_response, 'text', AGENTE_BOT = "Bot")

    prompt_type  = "prompt_ia_yes"

    send_ia_message(
        ESTADO_USUARIO=ESTADO_USUARIO,
        telefono_id=telefono_id,
        message_text=mensaje_procesado,
        lang=lang,
        prompt_type=prompt_type
        )


def send_message_and_log(ESTADO_USUARIO, telefono_id, message_text, message_type='text', button_titles=None, button_ids=None, list_titles=None, list_ids=None, list_descrip=None, AGENTE_BOT=None, media_url=None):
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
                "footer": {"text": get_message("es", "list_footer_text")},
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
    
    elif message_type == 'image':
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono_id,
            "type": "image",
            "image": {
                "link": media_url or IMA_SALUDO_URL,
                "caption": message_text
            }
        }
 
    elif message_type == 'document':
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono_id,
            "type": "document",
            "document": {
                "link": media_url,
                "caption": message_text or ""
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

    #send_whatsapp_message(data)
    enviar_respuesta_y_registrar_en_zoho(telefono_id, data, AGENTE_BOT)

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


    