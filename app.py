from flask import Flask, render_template, request, redirect, jsonify
from urllib.parse import quote
import json
import os
from datetime import datetime
from werkzeug.utils import secure_filename
import re
import fitz  # PyMuPDF
from openai import OpenAI

# ========== CONFIGURAÇÃO DO APP ==========
app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'odt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ========== SISTEMA PLANILHA ==========
DADOS_PATH = os.path.join('dados', 'planilha.json')

def carregar_dados():
    if not os.path.exists(DADOS_PATH):
        return []
    with open(DADOS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def salvar_dados(dados):
    with open(DADOS_PATH, 'w', encoding='utf-8') as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

@app.route('/planilha')
def planilha():
    dados = carregar_dados()
    return render_template('planilha.html', dados=dados)

@app.route('/salvar', methods=['POST'])
def salvar():
    novos_dados = request.json.get('dados', [])
    salvar_dados(novos_dados)
    return jsonify({"status": "ok"})




























# ========== IMPORTA OPÇÕES DO SISTEMA RADAR ==========
from opcoes import opcoes  # deve conter o dicionário 'opcoes'

campos_multiplos = [
    'tiposDocumentos', 'tiposJusticas', 'naturezas', 'competencias', 'classes', 'assuntos',
    'situacoes', 'situacoesJulgamentos', 'sistemas', 'meios', 'comarcas',
    'orgaosJulgadores', 'magistrados', 'fases'
]

# ========== UTILITÁRIOS ==========
def arquivo_permitido(nome):
    return '.' in nome and nome.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def montar_url_radar(termo, filtros):
    parametros = []
    if termo:
        parametros.append(f"termo={quote(termo)}")
    for campo, valores in filtros.items():
        if valores:
            json_valores = json.dumps(valores, ensure_ascii=True)
            encoded = quote(json_valores, safe='')
            parametros.append(f"{campo}={encoded}")
    return f"https://radar.tjmg.jus.br/processos?{'&'.join(parametros)}"

def limpar_texto(texto):
    texto = re.sub(r'[^\x00-\x7F\u00A0-\u00FF\n\w\s.,;:?!ºªáàâãéèêíïóôõöúçÁÀÂÃÉÈÊÍÓÔÕÚÇ\-–—]', '', texto)
    texto = re.sub(r'\n{2,}', '\n\n', texto)
    texto = re.sub(r'[ ]{2,}', ' ', texto)
    return texto.strip()

# ========== INTEGRAÇÃO COM OPENROUTER ==========
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    ##api_key="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",
    API_KEY = os.environ.get("OPENROUTER_API_KEY")
)

with open("prompt_ia.txt", "r", encoding="utf-8") as f:
    prompt_base = f.read().strip()

def gerar_resumo_openrouter(texto):
    try:
        resposta = client.chat.completions.create(
            ##model="deepseek/deepseek-r1:free",
            model="meta-llama/llama-3.1-8b-instruct:free",
            messages=[
                {"role": "user", "content": f"{prompt_base}\n\n{texto}"}
            ],
            temperature=0.5
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        return f"Erro ao gerar resumo: {e}"

# ========== ROTAS PRINCIPAIS ==========
@app.route('/')
def home():
    return render_template('index.html')

# ========== SISTEMA RADAR ==========
@app.route('/pesquisa', methods=['GET', 'POST'])
def pesquisa():
    caminho_arquivo = os.path.join("dados", "historico.json")

    if not os.path.exists(caminho_arquivo):
        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            json.dump([], f)

    try:
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            historico = json.load(f)
    except json.JSONDecodeError:
        historico = []

    if request.method == 'POST':
        dados = request.form
        parametros = []

        for campo in campos_multiplos:
            valores = dados.getlist(campo)
            if valores:
                json_valores = json.dumps(valores, ensure_ascii=True)
                encoded = quote(json_valores, safe='')
                parametros.append(f"{campo}={encoded}")

        termo_lista = dados.getlist("termo")
        termo = termo_lista[0] if termo_lista else ""
        if len(termo) > 200:
            termo = termo[:200]

        encoded_termo = quote(termo)
        parametros.append(f"termo={encoded_termo}")

        query_string = "&".join(parametros)
        url = f"https://radar.tjmg.jus.br/processos?{query_string}"

        registro = {
            "data": datetime.now().strftime("%d/%m/%Y às %H:%M"),
            "termo": termo,
            "filtros": {campo: dados.getlist(campo) for campo in campos_multiplos if dados.getlist(campo)}
        }

        historico.append(registro)
        historico = historico[-500:]

        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)

        return redirect(url)

    ultimos = historico[-10:][::-1]
    for item in ultimos:
        item["url"] = montar_url_radar(item["termo"], item["filtros"])
    total_pesquisas = len(historico)

    return render_template("pesquisa.html", opcoes=opcoes, ultimos=ultimos, total_pesquisas=total_pesquisas)

# ========== SISTEMA RELATOR ==========
@app.route('/pdf', methods=['GET', 'POST'])
def extrair_pdf():
    texto_extraido = ""

    if request.method == 'POST':
        if 'arquivo' not in request.files:
            return "Nenhum arquivo enviado", 400

        arquivo = request.files['arquivo']
        if arquivo.filename == '':
            return "Nome de arquivo vazio", 400

        if arquivo and arquivo_permitido(arquivo.filename):
            nome_seguro = secure_filename(arquivo.filename)
            caminho_pdf = os.path.join(app.config['UPLOAD_FOLDER'], nome_seguro)
            arquivo.save(caminho_pdf)

            doc = fitz.open(caminho_pdf)
            for pagina in doc:
                texto_extraido += pagina.get_text() + "\n"
            doc.close()

            os.remove(caminho_pdf)
            texto_extraido = limpar_texto(texto_extraido)

    return render_template('pdf.html', texto=texto_extraido)

# ========== ROTA DE RESUMO COM IA ==========
@app.route('/resumo', methods=['POST'])
def resumo():
    texto = request.form.get('texto', '').strip()
    if not texto:
        return "Texto vazio", 400
    if len(texto) > 80000:
        return "Texto muito longo para resumo automático.", 400

    resumo = gerar_resumo_openrouter(texto)
    return resumo

# ========== EXECUÇÃO ==========
#if __name__ == '__main__':
 #   app.run(debug=True)
