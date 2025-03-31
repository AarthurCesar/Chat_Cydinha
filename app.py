import tempfile
import os
import json
from flask import Flask, request, jsonify, session, render_template, send_from_directory
from flask_session import Session
from flask_cors import CORS
from werkzeug.utils import secure_filename
import PyPDF2
import requests
from dotenv import load_dotenv
import mimetypes
from datetime import datetime, timedelta

# Configuração inicial
app = Flask(__name__)
load_dotenv()
CORS(app)
PERSONALIDADE = os.getenv("PERSONALIDADE")

# Configurações
app.config.update({
    'SESSION_TYPE': 'filesystem',
    'SESSION_PERMANENT': False,  # Sessão não persiste após fechar o navegador
    'PERMANENT_SESSION_LIFETIME': timedelta(hours=24),  # 24 horas de persistência se o navegador permanecer aberto
    'SESSION_FILE_DIR': tempfile.mkdtemp(),
    'UPLOAD_FOLDER': tempfile.mkdtemp(),
    'SECRET_KEY': os.getenv('FLASK_SECRET_KEY', 'segredo-dev'),
    'MAX_CONTENT_LENGTH': 8 * 1024 * 1024  # 8MB
})
Session(app)

# Variáveis Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

#Garantindo formataçao def formatar_personalidade(texto):
def formatar_personalidade(texto):
    return texto.replace('\\n', '\n')

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf', 'txt'}

def validate_file_mime(filepath):
    mime, _ = mimetypes.guess_type(filepath)
    return mime in ['application/pdf', 'text/plain']

def extract_text_from_file(filepath):
    if filepath.endswith('.pdf'):
        text = ""
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = "\n".join(page.extract_text() for page in reader.pages)
        return text
    elif filepath.endswith('.txt'):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def init_history():
    if 'chat_history' not in session:
        personalidade = formatar_personalidade(PERSONALIDADE)
        session['chat_history'] = [{
            "role": "system", 
            "content": personalidade
        }]

# Rotas
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route("/chat", methods=["POST"])
def chat():
    try:
        init_history()
        file_content = ""
        file = request.files.get('file')
        
        # Processar arquivo
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            if not validate_file_mime(filepath):
                os.remove(filepath)
                return jsonify({"error": "Tipo de arquivo não permitido"}), 400
                
            file_content = extract_text_from_file(filepath)
            os.remove(filepath)

        # Obter mensagem
        user_message = request.form.get('message', '').strip()
        if not user_message and not file_content:
            return jsonify({"error": "Mensagem vazia"}), 400

        # Combinar conteúdo
        full_message = f"{file_content}\n{user_message}".strip()
        session['chat_history'].append({"role": "user", "content": full_message})

        # Chamada à API Groq
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3-70b-8192",
            "messages": session['chat_history'],
            "temperature": 0.7,
            "max_tokens": 1024
        }

        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        bot_response = response.json()['choices'][0]['message']['content']
        session['chat_history'].append({"role": "assistant", "content": bot_response})

        return jsonify({
            "response": bot_response,
            "status": "success"
        })

    except requests.exceptions.RequestException as e:
        if hasattr(e, 'response') and e.response.status_code == 429:
            return jsonify({
                "error": "Muitas requisições. Por favor, espere um momento.",
                "status": "error",
                "retry_after": 60
            }), 429
        return jsonify({"error": str(e), "status": "error"}), 500
    except Exception as e:
        return jsonify({"error": str(e), "status": "error"}), 500

@app.route("/reset", methods=["POST"])
def reset_chat():
    session.pop('chat_history', None)
    init_history()
    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)