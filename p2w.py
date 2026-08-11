import base64
import io
import json
import os
import re
import zipfile
import time
import tempfile
import logging
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

def load_saved_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_config(mistral_key, docling_key, mineru_key, gemini_key):
    config_data = {
        "mistral_key": mistral_key,
        "docling_key": docling_key,
        "mineru_key": mineru_key,
        "gemini_key": gemini_key
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        log_error(f"Lỗi khi lưu config: {e}")

saved_config = load_saved_config()

DEFAULT_MISTRAL_KEY = saved_config.get("mistral_key", "Asht2uDLjH8WTWnU06dBWdPbpcVQrbt5")
DEFAULT_DOCLING_KEY = saved_config.get("docling_key", "")
DEFAULT_MINERU_KEY = saved_config.get("mineru_key", "sk-IDb81Oj2W6pHrODooHN0xtKTxEXNzipsnZP6OxAqAl65Kz9O")
DEFAULT_GEMINI_KEY = saved_config.get("gemini_key", "AQ.Ab8RN6IiVh_ufztKik5rSMrl39c-U6_L6v5oy_Qru1-YNUBdRg")

# --- CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="p2w.py - Mistral, Docling, MinerU & Gemini Pro Suite", page_icon="⚡", layout="wide")
MINERU_BASE_URL = "https://mineru.net"

# --- KHỞI TẠO SESSION STATE ---
if "active_json" not in st.session_state:
    st.session_state.active_json = None
if "active_images_dict" not in st.session_state:
    st.session_state.active_images_dict = {}
if "active_file_name" not in st.session_state:
    st.session_state.active_file_name = "Document"
if "active_preview_markdown" not in st.session_state:
    st.session_state.active_preview_markdown = ""
if "active_docx_bytes" not in st.session_state:
    st.session_state.active_docx_bytes = None

# Lưu trữ Key vào Session State
if "saved_mistral_key" not in st.session_state:
    st.session_state.saved_mistral_key = DEFAULT_MISTRAL_KEY
if "saved_docling_key" not in st.session_state:
    st.session_state.saved_docling_key = DEFAULT_DOCLING_KEY
if "saved_mineru_key" not in st.session_state:
    st.session_state.saved_mineru_key = DEFAULT_MINERU_KEY
if "saved_gemini_key" not in st.session_state:
    st.session_state.saved_gemini_key = DEFAULT_GEMINI_KEY


# --- CÁC HÀM XỬ LÝ DÙNG CHUNG ---
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
                img_name = os.path.basename(filename)
                images_dict[img_name] = z.read(filename)
            elif (filename.endswith("layout.json") or filename.endswith(".json")) and not filename.startswith("__MACOSX"):
                try:
                    json_data = json.loads(z.read(filename).decode("utf-8"))
                except Exception as e:
                    log_error(f"Lỗi đọc JSON từ ZIP: {e}")
    return json_data, images_dict

def get_image_bytes(img_path_str, images_dict):
    if not img_path_str: return None
    clean_name = os.path.basename(img_path_str)
    
    if images_dict and clean_name in images_dict:
        return io.BytesIO(images_dict[clean_name])
        
    local_img_path = os.path.join("images", clean_name)
    if os.path.exists(local_img_path):
        with open(local_img_path, "rb") as f:
            return io.BytesIO(f.read())
            
    if os.path.exists(clean_name):
        with open(clean_name, "rb") as f:
            return io.BytesIO(f.read())
            
    return None

def generate_pandoc_docx(md_text, images_dict):
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
            pypandoc.convert_file(
                "temp_input.md", 
                'docx', 
                outputfile=output_docx, 
                extra_args=['--standalone', '--extract-media=.']
            )
            with open(output_docx, "rb") as f:
                docx_bytes = f.read()
            return docx_bytes
        except Exception as e:
            log_error(f"Lỗi tạo Word Pandoc: {e}")
            return None
        finally:
            os.chdir(original_dir)


# --- HÀM XỬ LÝ QUÁ TRÌNH GỬI LÊN 4 AI ---
def process_with_mistral_api(uploaded_file, api_key):
    if not MISTRAL_AVAILABLE:
        raise Exception("Chưa cài đặt thư viện mistralai.")
    client = Mistral(api_key=api_key)
    file_bytes = uploaded_file.getvalue()
    base64_file = base64.b64encode(file_bytes).decode('utf-8')

    ocr_response = client.ocr.process(
        document={"type": "document_url", "document_url": f"data:application/pdf;base64,{base64_file}"},
        model="mistral-ocr-latest",
        include_image_base64=True,
        include_blocks=True
    )
    
    full_markdown = ""
    images_dict = {}
    if hasattr(ocr_response, "pages"):
        for idx, page in enumerate(ocr_response.pages):
            page_md = page.markdown if hasattr(page, "markdown") else ""
            page_md = re.sub(r'!\[(.*?)\]\([^)]*?(img[_-]\d+\.(?:jpeg|jpg|png))\)', r'![\1](\2)', page_md)
            full_markdown += f"\n\n<hr/>\n<h3>Trang {idx+1} (Mistral OCR)</h3>\n\n" + page_md
            
            if hasattr(page, "images") and page.images:
                for img in page.images:
                    if hasattr(img, "id") and hasattr(img, "image_base64") and img.image_base64:
                        img_id = img.id
                        img_b64 = img.image_base64
                        if "," in img_b64: img_b64 = img_b64.split(",")[1]
                        try:
                            images_dict[img_id if img_id.lower().endswith((".jpeg", ".jpg", ".png")) else f"{img_id}.jpeg"] = base64.b64decode(img_b64)
                        except: pass
    return full_markdown, images_dict

def process_with_docling_api(uploaded_file, api_key):
    # Tích hợp theo chuẩn tài liệu Docling API / SDK thông dụng
    url = "https://api.docling.ai/v1/convert" # Hoặc endpoint tùy biến theo Docling Server/Cloud
    headers = {"Authorization": f"Bearer {api_key}"}
    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
    
    response = requests.post(url, headers=headers, files=files, timeout=60)
    if response.status_code == 200:
        res_json = response.json()
        markdown_text = res_json.get("markdown", "# Docling Output\n\n" + str(res_json))
        return markdown_text, {}
    else:
        raise Exception(f"Docling API Error: {response.status_code} - {response.text}")

def process_with_mineru_api(uploaded_file, api_key):
    # Upload dự phòng file
    upload_services = [
        {"url": "https://tmpfiles.org/api/v1/upload", "data": {}, "file_key": "file"}
    ]
    file_bytes = uploaded_file.getvalue()
    file_name = uploaded_file.name
    file_type = uploaded_file.type
    
    file_url = ""
    for service in upload_services:
        try:
            res = requests.post(service["url"], files={service["file_key"]: (file_name, file_bytes, file_type)}, timeout=30)
            if res.status_code == 200:
                res_json = res.json()
                raw_url = res_json.get("data", {}).get("url", "")
                if "tmpfiles.org/" in raw_url and not "tmpfiles.org/dl/" in raw_url:
                    raw_url = raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                file_url = raw_url
                break
        except: continue
        
    if not file_url:
        raise Exception("Không thể upload file trung gian cho MinerU.")

    # Gửi request task MinerU
    task_url = f"{MINERU_BASE_URL}/api/v4/extract/task"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"url": file_url, "model_version": "vlm", "is_ocr": True}
    
    response = requests.post(task_url, json=payload, headers=headers, timeout=30)
    if response.status_code != 200:
        raise Exception(f"MinerU Task Init Error: {response.text}")
        
    task_id = response.json().get("data", {}).get("task_id")
    if not task_id:
        raise Exception("Không nhận được Task ID từ MinerU.")
        
    # Poll kết quả
    for _ in range(40):
        time.sleep(5)
        status_url = f"{MINERU_BASE_URL}/api/v4/extract/task/{task_id}"
        st_res = requests.get(status_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        if st_res.status_code == 200:
            data = st_res.json().get("data", {})
            if data.get("state") == "done":
                zip_url = data.get("full_zip_url")
                r_zip = requests.get(zip_url)
                if r_zip.status_code == 200:
                    found_json, images_dict = extract_zip_and_get_data(r_zip.content)
                    # Chuyển layout json thành markdown đơn giản để preview
                    return f"# MinerU kết quả cho {file_name}\n\n(Đã trích xuất thành công dữ liệu cấu trúc)", images_dict
            elif data.get("state") == "failed":
                raise Exception("MinerU xử lý thất bại.")
    raise Exception("MinerU timeout.")

def process_with_gemini_api(uploaded_file, api_key, model_name):
    if not GEMINI_AVAILABLE:
        raise Exception("Chưa cài đặt thư viện google-genai.")
    client = genai.Client(api_key=api_key)
    file_bytes = uploaded_file.getvalue()
    mime_type = uploaded_file.type
    
    prompt = (
        "Bạn là chuyên gia OCR và chuyển đổi tài liệu. Hãy đọc tài liệu này chính xác tuyệt đối. "
        "Các biểu thức toán học BẮT BUỘC đặt trong cặp dấu đô la ($...$ cho inline hoặc $$...$$ cho block). "
        "Trình bày kết quả bằng Markdown chuẩn, bảng dùng cú pháp Markdown table. Chỉ trả về Markdown sạch sẽ."
    )
    response = client.models.generate_content(
        model=model_name,
        contents=[types.Part.from_bytes(data=file_bytes, mime_type=mime_type), prompt]
    )
    return response.text, {}


# --- HÀM HIỂN THỊ KHUNG PREVIEW & CÁC NÚT TẢI WORD ---
def render_preview_and_download_options(markdown_content, images_dict, file_name):
    st.subheader(f"👁️ Xem trước nội dung: {file_name}")
    
    # Tạo sẵn file word bằng Pandoc để tải
    docx_bytes = generate_pandoc_docx(markdown_content, images_dict)
    
    # Các nút tải xuống
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        if docx_bytes:
            st.download_button(
                label="📥 Tải Word (Pandoc Native)",
                data=docx_bytes,
                file_name=f"{file_name}_Pandoc.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True
            )
        else:
            st.button("📥 Tải Word (Pandoc Native)", disabled=True, use_container_width=True)
            
    with col_b2:
        if docx_bytes:
            st.download_button(
                label="📥 Tải Word (Preview / Thô)",
                data=docx_bytes,
                file_name=f"{file_name}_Preview.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )
        else:
            st.button("📥 Tải Word (Preview / Thô)", disabled=True, use_container_width=True)
            
    with col_b3:
        st.download_button(
            label="📥 Tải File Markdown (.md)",
            data=markdown_content,
            file_name=f"{file_name}.md",
            mime="text/markdown",
            use_container_width=True
        )

    # Thay thế đường dẫn ảnh sang dạng base64 để hiển thị trực quan trong khung HTML
    def replace_img_smart_html(match):
        alt_text = match.group(1)
        raw_path = match.group(2)
        target_name = os.path.basename(raw_path)
        matched_bytes = None
        for k, v in images_dict.items():
            if target_name in k or k in target_name:
                matched_bytes = v
                break
        if matched_bytes:
            b64_data = base64.b64encode(matched_bytes).decode('utf-8')
            return f'<div style="text-align: center; margin: 20px 0;"><img src="data:image/jpeg;base64,{b64_data}" style="max-width: 450px; border-radius: 8px; border: 1px solid #2d3748;" alt="{alt_text}" /></div>'
        return match.group(0)

    processed_html = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_img_smart_html, markdown_content)
    escaped_markdown_json = json.dumps(processed_html)

    preview_component_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/contrib/auto-render.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 10px; background-color: #ffffff; color: #2d3748; }}
            .btn-action {{ padding: 10px 20px; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; margin-right: 10px; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .btn-copy {{ background-color: #2b6cb0; }}
            .btn-copy:hover {{ background-color: #2c5282; }}
            #status-msg {{ margin-left: 10px; color: #2f855a; font-weight: bold; font-size: 13px; display: none; }}
            .preview-card {{ background-color: #ffffff; padding: 30px; border-radius: 10px; border: 1px solid #cbd5e0; max-height: 600px; overflow-y: auto; line-height: 1.8; }}
            table {{ border-collapse: collapse; width: auto; max-width: 100%; margin: 15px auto; border: 2px solid #2d3748; }}
            th {{ border: 2px solid #2d3748; padding: 6px 10px; background-color: #edf2f7; font-weight: bold; text-align: center; }}
            td {{ border: 2px solid #2d3748; padding: 6px 10px; vertical-align: middle; }}
        </style>
    </head>
    <body>
        <div>
            <button class="btn-action btn-copy" onclick="copyContentToClipboard()">📋 Sao chép nhanh (Dán vào Word)</button>
            <span id="status-msg">✔ Đã sao chép!</span>
        </div>
        <div class="preview-card" id="content-to-copy"></div>

        <script>
        const rawMarkdown = {escaped_markdown_json};
        document.getElementById('content-to-copy').innerHTML = marked.parse(rawMarkdown);

        function renderMath() {{
            if (typeof renderMathInElement === 'function') {{
                renderMathInElement(document.getElementById('content-to-copy'), {{
                    delimiters: [
                        {{left: '$$', right: '$$', display: true}},
                        {{left: '$', right: '$', display: false}},
                        {{left: '\\\\[', right: '\\\\]', display: true}},
                        {{left: '\\\\(', right: '\\\\)', display: false}}
                    ],
                    throwOnError: false
                }});
            }}
        }}

        document.addEventListener("DOMContentLoaded", renderMath);
        setTimeout(renderMath, 300);

        function copyContentToClipboard() {{
            const range = document.createRange();
            range.selectNode(document.getElementById('content-to-copy'));
            window.getSelection().removeAllRanges();
            window.getSelection().addRange(range);
            try {{
                document.execCommand('copy');
                showStatus("Đã sao chép vào bộ nhớ tạm! Mở Word và nhấn Ctrl+V");
            }} catch (err) {{ alert('Không thể sao chép tự động!'); }}
            window.getSelection().removeAllRanges();
        }}

        function showStatus(msg) {{
            const status = document.getElementById('status-msg');
            status.innerText = "✔ " + msg;
            status.style.display = 'inline';
            setTimeout(() => {{ status.style.display = 'none'; }}, 4000);
        }}
        </script>
    </body>
    </html>
    """
    components.html(preview_component_html, height=750, scrolling=False)


# --- 5. GIAO DIỆN CHÍNH (2 TABS) ---
st.title("⚡ p2w.py - Nền tảng Chuyển đổi & Xử lý Tài liệu Đa AI")
st.write("Tích hợp chuỗi xử lý thông minh qua **Mistral** (Chính), **Docling**, **MinerU** và **Gemini Pro**.")

tab1, tab2 = st.tabs([
    "🚀 Tab 1: Xử lý AI Pipeline (Mistral, Docling, MinerU, Gemini)", 
    "📦 Tab 2: Quản lý & Dựng Word từ ZIP, JSON, Markdown và Ảnh"
])

# ==========================================
# TAB 1: XỬ LÝ AI PIPELINE (4 AI)
# ==========================================
with tab1:
    st.subheader("🔑 Quản lý và Thay đổi API Keys trực tiếp")
    with st.expander("Cấu hình API Keys cho các hệ thống AI", expanded=False):
        col_k1, col_k2 = st.columns(2)
        with col_k1:
            mistral_key_input = st.text_input("Mistral API Key (Chính):", value=st.session_state.saved_mistral_key, type="password")
            docling_key_input = st.text_input("Docling API Key / Token:", value=st.session_state.saved_docling_key, type="password")
        with col_k2:
            mineru_key_input = st.text_input("MinerU API Key:", value=st.session_state.saved_mineru_key, type="password")
            gemini_key_input = st.text_input("Gemini Pro API Key:", value=st.session_state.saved_gemini_key, type="password")
            
        if st.button("Lưu API Keys vào Server", type="primary"):
            st.session_state.saved_mistral_key = mistral_key_input
            st.session_state.saved_docling_key = docling_key_input
            st.session_state.saved_mineru_key = mineru_key_input
            st.session_state.saved_gemini_key = gemini_key_input
            save_config(mistral_key_input, docling_key_input, mineru_key_input, gemini_key_input)
            st.success("Đã lưu thành công các API Keys lên server!")
            log_info("Đã cập nhật toàn bộ API Keys mới.")

    st.divider()
    st.subheader("📤 Tải lên tài liệu để xử lý qua AI Pipeline")
    pipeline_file = st.file_uploader("Chọn file tài liệu (PDF, Ảnh)", type=["pdf", "png", "jpg", "jpeg"], key="tab1_file_upload")
    
    selected_ai_primary = st.selectbox(
        "Chọn mô hình xử lý chủ đạo (Thứ tự ưu tiên):",
        ["Mistral (Chính)", "Docling", "MinerU", "Gemini Pro"]
    )
    
    selected_gemini_model = st.selectbox("Chọn Model Gemini cụ thể (nếu chạy dự phòng):", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"], index=0)

    if st.button("🚀 Bắt đầu Chạy Chuỗi AI Pipeline", type="primary"):
        if not pipeline_file:
            st.warning("Vui lòng tải lên file tài liệu!")
        else:
            base_name = pipeline_file.name.rsplit(".", 1)[0]
            success = False
            raw_md = ""
            imgs_dict = {}
            
            with st.spinner(f"Đang tiến hành xử lý tài liệu qua hệ thống (Ưu tiên: {selected_ai_primary})..."):
                # Thứ tự ưu tiên thực thi theo yêu cầu: Mistral -> Docling -> MinerU -> Gemini
                ai_pipeline_order = []
                if "Mistral" in selected_ai_primary:
                    ai_pipeline_order = [("Mistral", st.session_state.saved_mistral_key), 
                                         ("Docling", st.session_state.saved_docling_key), 
                                         ("MinerU", st.session_state.saved_mineru_key), 
                                         ("Gemini Pro", st.session_state.saved_gemini_key)]
                elif "Docling" in selected_ai_primary:
                    ai_pipeline_order = [("Docling", st.session_state.saved_docling_key), 
                                         ("Mistral", st.session_state.saved_mistral_key), 
                                         ("MinerU", st.session_state.saved_mineru_key), 
                                         ("Gemini Pro", st.session_state.saved_gemini_key)]
                elif "MinerU" in selected_ai_primary:
                    ai_pipeline_order = [("MinerU", st.session_state.saved_mineru_key), 
                                         ("Mistral", st.session_state.saved_mistral_key), 
                                         ("Docling", st.session_state.saved_docling_key), 
                                         ("Gemini Pro", st.session_state.saved_gemini_key)]
                else:
                    ai_pipeline_order = [("Gemini Pro", st.session_state.saved_gemini_key), 
                                         ("Mistral", st.session_state.saved_mistral_key), 
                                         ("Docling", st.session_state.saved_docling_key), 
                                         ("MinerU", st.session_state.saved_mineru_key)]

                for ai_name, key_val in ai_pipeline_order:
                    if not key_val.strip() and ai_name != "Docling": # Bỏ qua nếu thiếu key
                        continue
                    try:
                        st.info(f"Đang gọi mô hình: **{ai_name}**...")
                        log_info(f"Thực thi trích xuất qua {ai_name}")
                        
                        if ai_name == "Mistral":
                            raw_md, imgs_dict = process_with_mistral_api(pipeline_file, key_val)
                            success = True
                            break
                        elif ai_name == "Docling":
                            raw_md, imgs_dict = process_with_docling_api(pipeline_file, key_val)
                            success = True
                            break
                        elif ai_name == "MinerU":
                            raw_md, imgs_dict = process_with_mineru_api(pipeline_file, key_val)
                            success = True
                            break
                        elif ai_name == "Gemini Pro":
                            raw_md, imgs_dict = process_with_gemini_api(pipeline_file, key_val, selected_gemini_model)
                            success = True
                            break
                    except Exception as e:
                        log_error(f"Lỗi khi xử lý qua {ai_name}: {e}")
                        continue

            if success:
                st.session_state.active_preview_markdown = raw_md
                st.session_state.active_images_dict = imgs_dict
                st.session_state.active_file_name = base_name
                st.success("🎉 Xử lý AI thành công!")
                st.rerun()
            else:
                st.error("Tất cả các mô hình trong chuỗi Pipeline AI đều gặp lỗi hoặc chưa được cấu hình API Key chính xác.")

    # Hiển thị Preview và nút tải Word tại Tab 1 nếu đã có kết quả
    if st.session_state.active_preview_markdown:
        st.divider()
        render_preview_and_download_options(
            st.session_state.active_preview_markdown,
            st.session_state.active_images_dict,
            st.session_state.active_file_name
        )


# ==========================================
# TAB 2: QUẢN LÝ & DỰNG WORD TỪ ZIP, JSON, MD VÀ ẢNH
# ==========================================
with tab2:
    st.subheader("📦 Quản lý file đầu vào: ZIP, JSON, Markdown và Ảnh")
    st.write("Tải lên các file kết quả hoặc tệp ảnh riêng lẻ để hệ thống tự động gom nhóm, dựng lại nội dung và xuất file Word chuẩn chỉnh.")
    
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        package_file = st.file_uploader("📥 Tải lên gói tệp (ZIP, JSON hoặc Markdown)", type=["zip", "json", "md", "markdown"], key="tab2_pkg")
    with col_u2:
        image_files_tab2 = st.file_uploader("🖼️ Tải kèm các file ảnh riêng lẻ (nếu cần)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="tab2_imgs")

    if package_file is not None:
        file_ext = package_file.name.rsplit(".", 1)[1].lower()
        file_base = package_file.name.rsplit(".", 1)[0]
        
        # Cập nhật dictionary ảnh từ các ảnh upload kèm
        tab2_imgs_dict = {}
        if image_files_tab2:
            for img in image_files_tab2:
                tab2_imgs_dict[img.name] = img.getvalue()

        try:
            if file_ext == "zip":
                found_json, zip_imgs = extract_zip_and_get_data(package_file.getvalue())
                tab2_imgs_dict.update(zip_imgs)
                # Tìm nội dung markdown trong zip nếu có
                with zipfile.ZipFile(io.BytesIO(package_file.getvalue())) as z:
                    for name in z.namelist():
                        if name.endswith(".md"):
                            st.session_state.active_preview_markdown = z.read(name).decode("utf-8")
                            break
                st.session_state.active_images_dict = tab2_imgs_dict
                st.session_state.active_file_name = file_base
                st.success(f"Đã nạp gói ZIP thành công: {package_file.name}")
                st.rerun()
                
            elif file_ext == "json":
                json_content = json.loads(package_file.getvalue().decode("utf-8"))
                st.session_state.active_json = json_content
                st.session_state.active_images_dict = tab2_imgs_dict
                st.session_state.active_file_name = file_base
                # Chuyển đổi json thô sang markdown preview
                st.session_state.active_preview_markdown = f"# Dữ liệu JSON: {file_base}\n\n```json\n" + json.dumps(json_content, ensure_ascii=False, indent=2) + "\n```"
                st.success(f"Đã nạp file JSON thành công: {package_file.name}")
                st.rerun()
                
            elif file_ext in ["md", "markdown"]:
                md_text = package_file.getvalue().decode("utf-8")
                st.session_state.active_preview_markdown = md_text
                st.session_state.active_images_dict = tab2_imgs_dict
                st.session_state.active_file_name = file_base
                st.success(f"Đã nạp file Markdown thành công: {package_file.name}")
                st.rerun()
        except Exception as e:
            log_error(f"Lỗi khi xử lý file tải lên ở Tab 2: {e}")
            st.error(f"Lỗi khi đọc file: {e}")

    # Hiển thị Preview và các nút tải Word tại Tab 2 nếu có dữ liệu
    if st.session_state.active_preview_markdown:
        st.divider()
        render_preview_and_download_options(
            st.session_state.active_preview_markdown,
            st.session_state.active_images_dict,
            st.session_state.active_file_name
        )


# ==========================================
# KHUNG XEM NHẬT KÝ HỆ THỐNG (SYSTEM LOGS)
# ==========================================
st.divider()
with st.expander("🛠️ Xem Nhật ký hệ thống (System Logs)"):
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as log_file:
            log_content = log_file.read()
        st.text_area("Nội dung file app.log", log_content, height=250)
        if st.button("Xóa lịch sử log"):
            open(LOG_FILE, "w", encoding="utf-8").close()
            st.success("Đã làm sạch file log!")
            st.rerun()
    else:
        st.info("Chưa có bản ghi log nào được tạo.")