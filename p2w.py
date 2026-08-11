import base64
import io
import json
import os
import re
import zipfile
import time
import tempfile
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import requests
import streamlit as st
import streamlit.components.v1 as components
import pypandoc

# --- CẤU HÌNH GHI FILE LOG ---
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "app.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)

def log_info(msg):
    logging.info(msg)

def log_error(msg):
    logging.error(msg)

# Import thư viện google-genai
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Import thư viện mistralai SDK
try:
    from mistralai.client import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

# --- CẤU HÌNH LƯU KEY RA FILE TRÊN SERVER ---
CONFIG_FILE = "p2w_config_keys.json"
MISTRAL_KEY_FILE = "api_key_Mistral.txt"

def load_saved_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def load_mistral_keys_from_file():
    if os.path.exists(MISTRAL_KEY_FILE):
        try:
            with open(MISTRAL_KEY_FILE, "r", encoding="utf-8") as f:
                return f.read()
        except:
            pass
    return "Asht2uDLjH8WTWnU06dBWdPbpcVQrbt5"

def save_config(docling_key, mineru_key, gemini_key):
    config_data = {
        "docling_key": docling_key,
        "mineru_key": mineru_key,
        "gemini_key": gemini_key
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        log_error(f"Lỗi khi lưu config: {e}")

def save_mistral_keys_to_file(keys_text):
    try:
        with open(MISTRAL_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(keys_text)
    except Exception as e:
        log_error(f"Lỗi khi lưu file api_key_Mistral.txt: {e}")

saved_config = load_saved_config()

DEFAULT_DOCLING_KEY = saved_config.get("docling_key", "")
DEFAULT_MINERU_KEY = saved_config.get("mineru_key", "sk-IDb81Oj2W6pHrODooHN0xtKTxEXNzipsnZP6OxAqAl65Kz9O")
DEFAULT_GEMINI_KEY = saved_config.get("gemini_key", "AQ.Ab8RN6IiVh_ufztKik5rSMrl39c-U6_L6v5oy_Qru1-YNUBdRg")
DEFAULT_MISTRAL_KEYS_RAW = load_mistral_keys_from_file()

# --- CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="p2w.py - Multi-AI Concurrent & Rotation Suite", page_icon="⚡", layout="wide")
MINERU_BASE_URL = "https://mineru.net"
DOCLING_BASE_URL = "https://api.aws-c1.dcls.saas.ibm.com/20260811-1219-1052-8050-3cf005cc005c"

# --- KHỞI TẠO SESSION STATE ĐẦY ĐỦ AN TOÀN ---
if "mistral_key_editable" not in st.session_state: st.session_state.mistral_key_editable = False
if "docling_key_editable" not in st.session_state: st.session_state.docling_key_editable = False
if "mineru_key_editable" not in st.session_state: st.session_state.mineru_key_editable = False
if "gemini_key_editable" not in st.session_state: st.session_state.gemini_key_editable = False

if "saved_mistral_keys_raw" not in st.session_state: st.session_state.saved_mistral_keys_raw = DEFAULT_MISTRAL_KEYS_RAW
if "saved_docling_key" not in st.session_state: st.session_state.saved_docling_key = DEFAULT_DOCLING_KEY
if "saved_mineru_key" not in st.session_state: st.session_state.saved_mineru_key = DEFAULT_MINERU_KEY
if "saved_gemini_key" not in st.session_state: st.session_state.saved_gemini_key = DEFAULT_GEMINI_KEY

if "ai_results" not in st.session_state:
    st.session_state.ai_results = {
        "Mistral": {"json": None, "md": "", "imgs": {}, "name": "Document"},
        "Docling": {"json": None, "md": "", "imgs": {}, "name": "Document"},
        "MinerU": {"json": None, "md": "", "imgs": {}, "name": "Document"},
        "Gemini Pro": {"json": None, "md": "", "imgs": {}, "name": "Document"}
    }


# --- CÁC HÀM LÀM SẠCH LATEX & PREVIEW THÔNG MINH ---
def clean_markdown_for_preview(md_text):
    if not md_text:
        return ""
    # 1. Tránh lỗi ký tự % làm hỏng công thức
    cleaned = re.sub(r'(\d+)%', r'\1\\%', md_text)
    
    # 2. Thay thế các dạng ngoặc đơn chứa công thức như (\frac{...}{...}) thành $\frac{...}{...}$
    cleaned = re.sub(r'\(([a-zA-Z0-9\+\-\*\/\s\\\^\_\.\{\}]+?\\frac[^)]+?)\)', r'$\1$', cleaned)
    cleaned = re.sub(r'\(([a-zA-Z0-9\+\-\*\/\s\\\^\_\.\{\}]+?\\sqrt[^)]+?)\)', r'$\1$', cleaned)

    # 3. Tự động bọc các biểu thức toán học dạng phân số / căn thức độc lập chưa có dấu $
    cleaned = re.sub(r'(?<![\$\w])(\\frac\{[^}]+\}\{[^}]+\})', r'$\1$', cleaned)
    cleaned = re.sub(r'(?<![\$\w])(\\sqrt\{[^}]+\})', r'$\1$', cleaned)

    # 4. Chuẩn hóa hệ phương trình cases
    cleaned = re.sub(r'\\begin\{cases\}', r'$$\\begin{cases}', cleaned)
    cleaned = re.sub(r'\\end\{cases\}', r'\\end{cases}$$', cleaned)
    
    return cleaned

def clean_and_wrap_latex(latex_str):
    if not latex_str: return ""
    clean_str = latex_str.strip()
    if clean_str.startswith("$") and clean_str.endswith("$"):
        clean_str = clean_str[1:-1].strip()
    return f"${clean_str}$"

def extract_zip_and_get_data(zip_bytes):
    images_dict = {}
    json_data = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for filename in z.namelist():
            if "images/" in filename and not filename.endswith("/"):
                images_dict[os.path.basename(filename)] = z.read(filename)
            elif (filename.endswith("layout.json") or filename.endswith(".json")) and not filename.startswith("__MACOSX"):
                try:
                    json_data = json.loads(z.read(filename).decode("utf-8"))
                except Exception as e:
                    log_error(f"Lỗi đọc JSON từ ZIP: {e}")
    return json_data, images_dict

def generate_pandoc_docx(data, images_dict):
    md_text = ""
    if isinstance(data, dict):
        md_lines = []
        pages = data.get("pdf_info", [])
        for page in pages:
            if not isinstance(page, dict): continue
            for block in page.get("para_blocks", page.get("blocks", [])):
                if not isinstance(block, dict): continue
                b_type = block.get("type")
                if b_type in ["text", "title"]:
                    p_text = ""
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            content = span.get("content", span.get("text", ""))
                            if span.get("type") == "inline_equation":
                                p_text += f" {clean_and_wrap_latex(content)} "
                            else:
                                p_text += content
                    if p_text.strip():
                        md_lines.append(p_text.strip() + "\n\n")
        md_text = "".join(md_lines)
    else:
        md_text = str(data)

    md_text = clean_markdown_for_preview(md_text)

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_md_path = os.path.join(tmp_dir, "temp_input.md")
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        for img_name, img_bytes in images_dict.items():
            with open(os.path.join(tmp_dir, img_name), "wb") as img_f:
                img_f.write(img_bytes)
        original_dir = os.getcwd()
        os.chdir(tmp_dir)
        try:
            output_docx = "Output_Native.docx"
            pypandoc.convert_file("temp_input.md", 'docx', outputfile=output_docx, extra_args=['--standalone', '--extract-media=.'])
            with open(output_docx, "rb") as f:
                return f.read()
        except Exception as e:
            log_error(f"Lỗi tạo Word Pandoc: {e}")
            return None
        finally:
            os.chdir(original_dir)


# --- XỬ LÝ MISTRAL VỚI CƠ CHẾ XOAY VÒNG KEY TỪ api_key_Mistral.txt ---
def process_with_mistral_with_rotation(file_bytes, file_name, file_type, raw_keys_str):
    if not MISTRAL_AVAILABLE:
        raise Exception("Chưa cài đặt mistralai SDK.")
    
    key_list = [k.strip() for k in re.split(r'[,\n]', raw_keys_str) if k.strip()]
    if not key_list:
        raise Exception("Không tìm thấy Mistral API Key hợp lệ.")

    last_error = None
    for idx, api_key in enumerate(key_list):
        try:
            log_info(f"Đang thử xử lý Mistral OCR với Key số {idx + 1}...")
            client = Mistral(api_key=api_key)
            base64_file = base64.b64encode(file_bytes).decode('utf-8')
            
            ocr_response = client.ocr.process(
                document={"type": "document_url", "document_url": f"data:{file_type};base64,{base64_file}"},
                model="mistral-ocr-latest",
                include_image_base64=True,
                include_blocks=True
            )
            
            full_markdown = ""
            images_dict = {}
            if hasattr(ocr_response, "pages"):
                for p_idx, page in enumerate(ocr_response.pages):
                    page_md = page.markdown if hasattr(page, "markdown") else ""
                    full_markdown += f"\n\n<hr/>\n<h3>Trang {p_idx+1} (Mistral OCR)</h3>\n\n" + page_md
                    if hasattr(page, "images") and page.images:
                        for img in page.images:
                            if hasattr(img, "id") and hasattr(img, "image_base64") and img.image_base64:
                                img_id = img.id
                                img_b64 = img.image_base64
                                if "," in img_b64: img_b64 = img_b64.split(",")[1]
                                try:
                                    images_dict[img_id if img_id.lower().endswith((".jpeg", ".jpg", ".png")) else f"{img_id}.jpeg"] = base64.b64decode(img_b64)
                                except: pass
            
            log_info(f"Mistral OCR thành công với Key số {idx + 1}")
            return None, clean_markdown_for_preview(full_markdown), images_dict
            
        except Exception as e:
            last_error = e
            log_error(f"Key số {idx + 1} lỗi: {str(e)}. Đang chuyển sang key tiếp theo...")
            continue
            
    raise Exception(f"Tất cả các Mistral Key đều thất bại. Lỗi cuối: {str(last_error)}")

def process_with_docling(file_bytes, file_name, file_type, api_key):
    url_convert = f"{DOCLING_BASE_URL}/v1/convert/file/async"
    headers = {"X-Api-Key": api_key} if api_key else {}
    files = {"files": (file_name, file_bytes, file_type)}
    
    response = requests.post(url_convert, headers=headers, files=files, timeout=60)
    if response.status_code != 200:
        raise Exception(f"Docling Convert Init Error: {response.status_code} - {response.text}")
        
    res_data = response.json()
    task_id = res_data.get("task_id") or res_data.get("id")
    if not task_id:
        raise Exception(f"Không nhận được task_id từ Docling: {res_data}")

    for _ in range(80):
        time.sleep(5)
        url_status = f"{DOCLING_BASE_URL}/v1/status/poll/{task_id}"
        st_res = requests.get(url_status, headers=headers, timeout=30)
        if st_res.status_code == 200:
            st_data = st_res.json()
            status = st_data.get("status") or st_data.get("state")
            if status == "success":
                url_result = f"{DOCLING_BASE_URL}/v1/result/{task_id}"
                res_fetch = requests.get(url_result, headers=headers, timeout=30)
                if res_fetch.status_code == 200:
                    result_json = res_fetch.json()
                    md = result_json.get("markdown", str(result_json))
                    return None, clean_markdown_for_preview(md), {}
            elif status == "failure" or status == "failed":
                raise Exception("Docling conversion task failed.")
    raise Exception("Docling polling timeout.")

def process_with_mineru(file_bytes, file_name, file_type, api_key):
    upload_url = "https://tmpfiles.org/api/v1/upload"
    res = requests.post(upload_url, files={"file": (file_name, file_bytes, file_type)}, timeout=30)
    if res.status_code != 200:
        raise Exception("Không thể upload file trung gian cho MinerU.")
    file_url = res.json().get("data", {}).get("url", "")
    if "tmpfiles.org/" in file_url and not "tmpfiles.org/dl/" in file_url:
        file_url = file_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")

    task_url = f"{MINERU_BASE_URL}/api/v4/extract/task"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"url": file_url, "model_version": "vlm", "is_ocr": True}
    
    response = requests.post(task_url, json=payload, headers=headers, timeout=30)
    if response.status_code != 200:
        raise Exception(f"MinerU Task Init Error: {response.text}")
        
    task_id = response.json().get("data", {}).get("task_id")
    for _ in range(40):
        time.sleep(5)
        status_url = f"{MINERU_BASE_URL}/api/v4/extract/task/{task_id}"
        st_res = requests.get(status_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        if st_res.status_code == 200:
            data = st_res.json().get("data", {})
            if data.get("state") == "done":
                r_zip = requests.get(data.get("full_zip_url"))
                if r_zip.status_code == 200:
                    found_json, images_dict = extract_zip_and_get_data(r_zip.content)
                    return found_json, "", images_dict
            elif data.get("state") == "failed":
                raise Exception("MinerU xử lý thất bại hoặc Token hết hạn (A0211).")
    raise Exception("MinerU timeout.")

def process_with_gemini(file_bytes, file_name, file_type, api_key, model_name):
    if not GEMINI_AVAILABLE:
        raise Exception("Chưa cài đặt google-genai.")
    os.environ["GEMINI_API_KEY"] = api_key
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=file_type),
            "Hãy đọc tài liệu này chính xác tuyệt đối. Biểu thức toán học đặt trong cặp đô la ($...$). Trình bày Markdown sạch sẽ."
        ]
    )
    return None, clean_markdown_for_preview(response.text), {}


# --- HÀM RENDER PREVIEW BOX ---
def render_ai_preview_box(ai_label, json_data, markdown_text, images_dict, file_name):
    st.subheader(f"📊 Kết quả từ: `{ai_label}`")
    
    data_source = json_data if json_data else markdown_text
    docx_bytes = generate_pandoc_docx(data_source, images_dict) if data_source else None

    col1, col2, col3 = st.columns(3)
    with col1:
        if docx_bytes:
            st.download_button(f"📥 Tải Word (Pandoc) [{ai_label}]", docx_bytes, f"{file_name}_{ai_label}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", type="primary", use_container_width=True, key=f"dl_{ai_label}")
    with col2:
        if markdown_text or json_data:
            md_dl = markdown_text if markdown_text else json.dumps(json_data, ensure_ascii=False, indent=2)
            st.download_button(f"📥 Tải File (.md/.json) [{ai_label}]", md_dl, f"{file_name}_{ai_label}.txt", "text/plain", use_container_width=True, key=f"dl_md_{ai_label}")
    with col3:
        if json_data:
            st.download_button(f"📥 Tải JSON [{ai_label}]", json.dumps(json_data, ensure_ascii=False, indent=2), f"{file_name}_{ai_label}.json", "application/json", use_container_width=True, key=f"dl_json_{ai_label}")

    content_to_render = markdown_text if markdown_text else json.dumps(json_data, ensure_ascii=False, indent=2)
    preview_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/contrib/auto-render.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 10px; background: #fff; color: #2d3748; }}
            .btn-action {{ padding: 8px 16px; color: white; background: #2b6cb0; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; margin-bottom: 10px; }}
            .preview-card {{ background: #fff; padding: 20px; border-radius: 8px; border: 1px solid #cbd5e0; max-height: 450px; overflow-y: auto; line-height: 1.6; }}
        </style>
    </head>
    <body>
        <button class="btn-action" onclick="copyContent()">📋 Sao chép nhanh [{ai_label}] (Dán Word)</button>
        <div class="preview-card" id="box_{ai_label}"></div>
        <script>
        document.getElementById('box_{ai_label}').innerHTML = marked.parse({json.dumps(content_to_render)});
        setTimeout(() => {{
            renderMathInElement(document.getElementById('box_{ai_label}'), {{
                delimiters: [
                    {{left: '$$', right: '$$', display: true}},
                    {{left: '$', right: '$', display: false}},
                    {{left: '\\\\(', right: '\\\\)', display: false}},
                    {{left: '\\\\[', right: '\\\\]', display: true}}
                ],
                throwOnError: false
            }});
        }}, 300);
        function copyContent() {{
            const range = document.createRange();
            range.selectNode(document.getElementById('box_{ai_label}'));
            window.getSelection().removeAllRanges();
            window.getSelection().addRange(range);
            document.execCommand('copy');
            window.getSelection().removeAllRanges();
            alert("Đã sao chép nội dung [{ai_label}]! Mở Word và nhấn Ctrl+V");
        }}
        </script>
    </body>
    </html>
    """
    components.html(preview_html, height=550, scrolling=False)


# --- GIAO DIỆN CHÍNH (2 TABS) ---
st.title("⚡ p2w.py - Nền tảng Xử lý Đồng thời & Xoay vòng Key Đa AI")
st.write("Hệ thống hỗ trợ chạy đồng thời/riêng lẻ qua **Mistral** (xoay vòng key từ `api_key_Mistral.txt`), **Docling**, **MinerU** và **Gemini Pro**.")

tab1, tab2 = st.tabs([
    "🚀 Tab 1: AI Pipeline (Xoay vòng Key Mistral & Điều khiển AI)", 
    "📦 Tab 2: Quản lý & Dựng Word từ ZIP, JSON, Markdown và Ảnh"
])

# ==========================================
# TAB 1: XỬ LÝ ĐỒNG THỜI HOẶC TỪNG AI RIÊNG LẺ
# ==========================================
with tab1:
    st.subheader("🔑 Cấu hình API Keys (Hỗ trợ Đổi và Lưu an toàn)")
    col_k1, col_k2 = st.columns(2)
    
    with col_k1:
        m_keys = st.text_input(
            "Danh sách Mistral API Keys (Đọc/Lưu từ `api_key_Mistral.txt`):", 
            value=st.session_state.saved_mistral_keys_raw, 
            type="password",
            disabled=not st.session_state.mistral_key_editable
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Đổi Mistral Keys", key="b_ed_m"): st.session_state.mistral_key_editable = True; st.rerun()
        with c2:
            if st.session_state.mistral_key_editable and st.button("Lưu Mistral Keys", key="b_sv_m"):
                st.session_state.saved_mistral_keys_raw = m_keys
                save_mistral_keys_to_file(m_keys)
                st.session_state.mistral_key_editable = False
                st.success("Đã lưu danh sách Mistral Keys vào file `api_key_Mistral.txt`!")
                st.rerun()

        d_key = st.text_input("Docling API Key (X-Api-Key):", value=st.session_state.saved_docling_key, type="password", disabled=not st.session_state.docling_key_editable)
        c3, c4 = st.columns(2)
        with c3:
            if st.button("Đổi Docling Key", key="b_ed_d"): st.session_state.docling_key_editable = True; st.rerun()
        with c4:
            if st.session_state.docling_key_editable and st.button("Lưu Docling Key", key="b_sv_d"):
                st.session_state.saved_docling_key = d_key
                save_config(st.session_state.saved_docling_key, st.session_state.saved_mineru_key, st.session_state.saved_gemini_key)
                st.session_state.docling_key_editable = False
                st.success("Đã lưu Docling Key!")
                st.rerun()

    with col_k2:
        mi_key = st.text_input("MinerU API Key:", value=st.session_state.saved_mineru_key, type="password", disabled=not st.session_state.mineru_key_editable)
        c5, c6 = st.columns(2)
        with c5:
            if st.button("Đổi MinerU Key", key="b_ed_mi"): st.session_state.mineru_key_editable = True; st.rerun()
        with c6:
            if st.session_state.mineru_key_editable and st.button("Lưu MinerU Key", key="b_sv_mi"):
                st.session_state.saved_mineru_key = mi_key
                save_config(st.session_state.saved_docling_key, st.session_state.saved_mineru_key, st.session_state.saved_gemini_key)
                st.session_state.mineru_key_editable = False
                st.success("Đã lưu MinerU Key!")
                st.rerun()

        g_key = st.text_input("Gemini API Key:", value=st.session_state.saved_gemini_key, type="password", disabled=not st.session_state.gemini_key_editable)
        c7, c8 = st.columns(2)
        with c7:
            if st.button("Đổi Gemini Key", key="b_ed_g"): st.session_state.gemini_key_editable = True; st.rerun()
        with c8:
            if st.session_state.gemini_key_editable and st.button("Lưu Gemini Key", key="b_sv_g"):
                st.session_state.saved_gemini_key = g_key
                save_config(st.session_state.saved_docling_key, st.session_state.saved_mineru_key, st.session_state.saved_gemini_key)
                st.session_state.gemini_key_editable = False
                st.success("Đã lưu Gemini Key!")
                st.rerun()

    st.divider()
    selected_gemini_model = st.selectbox("Chọn Model Gemini:", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"], index=0)
    pipeline_file = st.file_uploader("📥 Tải file tài liệu (PDF, Ảnh) để xử lý", type=["pdf", "png", "jpg", "jpeg"], key="tab1_upload")

    st.markdown("### 🎛️ Bảng điều khiển tác vụ AI (Chạy đồng thời hoặc chạy riêng lẻ từng AI)")
    
    col_btn_all, col_btn_m, col_btn_d, col_btn_mi, col_btn_g = st.columns(5)
    
    run_all = col_btn_all.button("🚀 Chạy Tất Cả (Đồng thời)", type="primary", use_container_width=True)
    run_mistral = col_btn_m.button("🌪️ Chỉ chạy Mistral", use_container_width=True)
    run_docling = col_btn_d.button("📄 Chỉ chạy Docling", use_container_width=True)
    run_mineru = col_btn_mi.button("📐 Chỉ chạy MinerU", use_container_width=True)
    run_gemini = col_btn_g.button("✨ Chỉ chạy Gemini", use_container_width=True)

    if pipeline_file and (run_all or run_mistral or run_docling or run_mineru or run_gemini):
        base_name = pipeline_file.name.rsplit(".", 1)[0]
        f_bytes = pipeline_file.getvalue()
        f_name = pipeline_file.name
        f_type = pipeline_file.type
        
        k_mistral_raw = st.session_state.saved_mistral_keys_raw
        k_docling = st.session_state.saved_docling_key
        k_mineru = st.session_state.saved_mineru_key
        k_gemini = st.session_state.saved_gemini_key
        
        all_tasks = {
            "Mistral": lambda: process_with_mistral_with_rotation(f_bytes, f_name, f_type, k_mistral_raw),
            "Docling": lambda: process_with_docling(f_bytes, f_name, f_type, k_docling),
            "MinerU": lambda: process_with_mineru(f_bytes, f_name, f_type, k_mineru),
            "Gemini Pro": lambda: process_with_gemini(f_bytes, f_name, f_type, k_gemini, selected_gemini_model)
        }

        if run_all:
            selected_tasks = all_tasks
        else:
            selected_tasks = {}
            if run_mistral: selected_tasks["Mistral"] = all_tasks["Mistral"]
            if run_docling: selected_tasks["Docling"] = all_tasks["Docling"]
            if run_mineru: selected_tasks["MinerU"] = all_tasks["MinerU"]
            if run_gemini: selected_tasks["Gemini Pro"] = all_tasks["Gemini Pro"]

        with st.spinner(f"⏳ Đang thực thi các mô hình AI đã chọn ({list(selected_tasks.keys())})..."):
            with ThreadPoolExecutor(max_workers=len(selected_tasks)) as executor:
                future_to_ai = {executor.submit(task_func): ai_name for ai_name, task_func in selected_tasks.items()}
                
                for future in as_completed(future_to_ai):
                    ai_name = future_to_ai[future]
                    try:
                        json_res, md_res, img_res = future.result()
                        st.session_state.ai_results[ai_name] = {
                            "json": json_res,
                            "md": md_res,
                            "imgs": img_res,
                            "name": base_name
                        }
                        log_info(f"AI {ai_name} hoàn thành thành công.")
                    except Exception as e:
                        err_msg = f"Lỗi xử lý: {str(e)}"
                        log_error(f"Lỗi AI {ai_name}: {err_msg}")
                        st.session_state.ai_results[ai_name] = {
                            "json": None,
                            "md": f"# Lỗi xử lý từ {ai_name}\n\n> {err_msg}",
                            "imgs": {},
                            "name": base_name
                        }

        st.success("🎉 Hoàn tất quá trình xử lý!")
        st.rerun()
    elif not pipeline_file and (run_all or run_mistral or run_docling or run_mineru or run_gemini):
        st.warning("Vui lòng tải lên file tài liệu trước khi bấm nút chạy!")

    # HIỂN THỊ 4 KHUNG PREVIEW ĐỘC LẬP
    if any(res.get("json") or res.get("md") for res in st.session_state.ai_results.values()):
        st.divider()
        st.subheader("📊 Khung Preview độc lập tương ứng của các AI")
        
        t_m, t_d, t_mi, t_g = st.tabs(["🌪️ Mistral OCR", "📄 Docling", "📐 MinerU", "✨ Gemini Pro"])
        
        with t_m:
            res = st.session_state.ai_results.get("Mistral", {})
            render_ai_preview_box("Mistral", res.get("json"), res.get("md"), res.get("imgs", {}), res.get("name", "Document"))
        with t_d:
            res = st.session_state.ai_results.get("Docling", {})
            render_ai_preview_box("Docling", res.get("json"), res.get("md"), res.get("imgs", {}), res.get("name", "Document"))
        with t_mi:
            res = st.session_state.ai_results.get("MinerU", {})
            render_ai_preview_box("MinerU", res.get("json"), res.get("md"), res.get("imgs", {}), res.get("name", "Document"))
        with t_g:
            res = st.session_state.ai_results.get("Gemini Pro", {})
            render_ai_preview_box("Gemini Pro", res.get("json"), res.get("md"), res.get("imgs", {}), res.get("name", "Document"))


# ==========================================
# TAB 2: QUẢN LÝ & DỰNG WORD TỪ ZIP, JSON, MD VÀ ẢNH
# ==========================================
with tab2:
    st.subheader("📦 Quản lý file đầu vào: ZIP, JSON, Markdown và Ảnh")
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        package_file = st.file_uploader("📥 Tải lên gói tệp (ZIP, JSON hoặc Markdown)", type=["zip", "json", "md", "markdown"], key="tab2_pkg")
    with col_u2:
        image_files_tab2 = st.file_uploader("🖼️ Tải kèm các file ảnh riêng lẻ (nếu cần)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="tab2_imgs")

    if package_file is not None:
        file_ext = package_file.name.rsplit(".", 1)[1].lower()
        file_base = package_file.name.rsplit(".", 1)[0]
        tab2_imgs_dict = {img.name: img.getvalue() for img in image_files_tab2} if image_files_tab2 else {}

        try:
            if file_ext == "zip":
                found_json, zip_imgs = extract_zip_and_get_data(package_file.getvalue())
                tab2_imgs_dict.update(zip_imgs)
                st.session_state.ai_results["MinerU"] = {"json": found_json, "md": "", "imgs": tab2_imgs_dict, "name": file_base}
                st.success("Đã nạp gói ZIP thành công vào hệ thống quản lý!")
                st.rerun()
            elif file_ext == "json":
                json_content = json.loads(package_file.getvalue().decode("utf-8"))
                st.session_state.ai_results["MinerU"] = {"json": json_content, "md": "", "imgs": tab2_imgs_dict, "name": file_base}
                st.success("Đã nạp file JSON thành công!")
                st.rerun()
            elif file_ext in ["md", "markdown"]:
                md_content = package_file.getvalue().decode("utf-8")
                st.session_state.ai_results["Mistral"] = {"json": None, "md": clean_markdown_for_preview(md_content), "imgs": tab2_imgs_dict, "name": file_base}
                st.success("Đã nạp file Markdown thành công!")
                st.rerun()
        except Exception as e:
            log_error(f"Lỗi khi đọc file ở Tab 2: {e}")
            st.error(f"Lỗi khi đọc file: {e}")

    st.divider()
    res_m = st.session_state.ai_results.get("Mistral", {})
    res_mu = st.session_state.ai_results.get("MinerU", {})
    if res_m.get("md"):
        render_ai_preview_box("Workspace Mistral", None, res_m.get("md"), res_m.get("imgs", {}), res_m.get("name", "Document"))
    if res_mu.get("json"):
        render_ai_preview_box("Workspace MinerU", res_mu.get("json"), "", res_mu.get("imgs", {}), res_mu.get("name", "Document"))

# --- XEM NHẬT KÝ HỆ THỐNG ---
st.divider()
with st.expander("🛠️ Xem Nhật ký hệ thống (System Logs)"):
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as log_file:
            st.text_area("Nội dung file app.log", log_file.read(), height=250)
        if st.button("Xóa lịch sử log"):
            open(LOG_FILE, "w", encoding="utf-8").close()
            st.success("Đã làm sạch file log!")
            st.rerun()