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
st.set_page_config(page_title="p2w.py - Multi-AI Document Suite", page_icon="⚡", layout="wide")
MINERU_BASE_URL = "https://mineru.net"

# --- KHỞI TẠO SESSION STATE CHO EDIT KEY ---
if "mistral_key_editable" not in st.session_state: st.session_state.mistral_key_editable = False
if "docling_key_editable" not in st.session_state: st.session_state.docling_key_editable = False
if "mineru_key_editable" not in st.session_state: st.session_state.mineru_key_editable = False
if "gemini_key_editable" not in st.session_state: st.session_state.gemini_key_editable = False

if "active_json" not in st.session_state: st.session_state.active_json = None
if "active_images_dict" not in st.session_state: st.session_state.active_images_dict = {}
if "active_file_name" not in st.session_state: st.session_state.active_file_name = "Document"
if "active_preview_markdown" not in st.session_state: st.session_state.active_preview_markdown = ""

# Lưu trữ Key vào Session State
if "saved_mistral_key" not in st.session_state: st.session_state.saved_mistral_key = DEFAULT_MISTRAL_KEY
if "saved_docling_key" not in st.session_state: st.session_state.saved_docling_key = DEFAULT_DOCLING_KEY
if "saved_mineru_key" not in st.session_state: st.session_state.saved_mineru_key = DEFAULT_MINERU_KEY
if "saved_gemini_key" not in st.session_state: st.session_state.saved_gemini_key = DEFAULT_GEMINI_KEY

# Lưu trữ kết quả của 4 AI độc lập phục vụ 4 khung preview
if "ai_results" not in st.session_state:
    st.session_state.ai_results = {
        "Mistral": {"md": "", "imgs": {}},
        "Docling": {"md": "", "imgs": {}},
        "MinerU": {"md": "", "imgs": {}},
        "Gemini Pro": {"md": "", "imgs": {}}
    }


# --- CÁC HÀM XỬ LÝ DÙNG CHUNG ---
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


# --- XỬ LÝ 4 AI RIÊNG BIỆT ---
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
    # Cấu hình chuẩn theo tài liệu Docling SaaS Developer
    url = "https://developer.dcls.saas.ibm.com/v1/convert"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
    
    try:
        response = requests.post(url, headers=headers, files=files, timeout=60, verify=True)
    except:
        # Fallback nếu gặp lỗi chứng chỉ SSL trên môi trường mạng cụ thể
        response = requests.post(url, headers=headers, files=files, timeout=60, verify=False)
        
    if response.status_code == 200:
        res_json = response.json()
        return res_json.get("markdown", "# Docling Output\n\n" + str(res_json)), {}
    else:
        raise Exception(f"Docling API Error: {response.status_code} - {response.text}")

def process_with_mineru_api(uploaded_file, api_key):
    upload_url = "https://tmpfiles.org/api/v1/upload"
    file_bytes = uploaded_file.getvalue()
    file_name = uploaded_file.name
    file_type = uploaded_file.type
    
    res = requests.post(upload_url, files={"file": (file_name, file_bytes, file_type)}, timeout=30)
    if res.status_code != 200:
        raise Exception("Không thể upload file trung gian cho MinerU.")
    
    res_json = res.json()
    file_url = res_json.get("data", {}).get("url", "")
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
                    return f"# MinerU kết quả cho {file_name}\n\n(Đã trích xuất cấu trúc thành công qua MinerU)", images_dict
            elif data.get("state") == "failed":
                raise Exception("MinerU xử lý thất bại hoặc Token hết hạn.")
    raise Exception("MinerU timeout.")

def process_with_gemini_api(uploaded_file, api_key, model_name):
    if not GEMINI_AVAILABLE:
        raise Exception("Chưa cài đặt thư viện google-genai.")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_bytes(data=uploaded_file.getvalue(), mime_type=uploaded_file.type),
            "Hãy đọc tài liệu này chính xác tuyệt đối. Biểu thức toán học đặt trong cặp dấu đô la ($...$). Trình bày Markdown sạch sẽ."
        ]
    )
    return response.text, {}


# --- HÀM HIỂN THỊ KHUNG PREVIEW & CÁC NÚT TẢI WORD CHO TỪNG AI ---
def render_preview_and_download_options(markdown_content, images_dict, file_name, ai_label="AI"):
    if not markdown_content:
        st.info(f"Chưa có dữ liệu kết quả từ **{ai_label}**.")
        return
        
    st.markdown(f"### 👁️ Xem trước kết quả trích xuất từ: `{ai_label}`")
    docx_bytes = generate_pandoc_docx(markdown_content, images_dict)
    
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        if docx_bytes:
            st.download_button(f"📥 Tải Word (Pandoc Native) [{ai_label}]", docx_bytes, f"{file_name}_{ai_label}_Pandoc.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", type="primary", use_container_width=True, key=f"dl_pandoc_{ai_label}")
        else:
            st.button(f"📥 Tải Word (Pandoc Native) [{ai_label}]", disabled=True, use_container_width=True, key=f"dl_pandoc_dis_{ai_label}")
    with col_b2:
        if docx_bytes:
            st.download_button(f"📥 Tải Word (Preview / Thô) [{ai_label}]", docx_bytes, f"{file_name}_{ai_label}_Preview.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True, key=f"dl_prev_{ai_label}")
        else:
            st.button(f"📥 Tải Word (Preview / Thô) [{ai_label}]", disabled=True, use_container_width=True, key=f"dl_prev_dis_{ai_label}")
    with col_b3:
        st.download_button(f"📥 Tải File Markdown (.md) [{ai_label}]", markdown_content, f"{file_name}_{ai_label}.md", "text/markdown", use_container_width=True, key=f"dl_md_{ai_label}")

    def replace_img_smart_html(match):
        alt_text = match.group(1)
        target_name = os.path.basename(match.group(2))
        matched_bytes = images_dict.get(target_name)
        if matched_bytes:
            b64_data = base64.b64encode(matched_bytes).decode('utf-8')
            return f'<div style="text-align: center; margin: 20px 0;"><img src="data:image/jpeg;base64,{b64_data}" style="max-width: 450px; border-radius: 8px;" alt="{alt_text}" /></div>'
        return match.group(0)

    processed_html = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_img_smart_html, markdown_content)
    
    unique_key = f"preview_{ai_label.lower().replace(' ', '_')}"
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
            body {{ font-family: Arial, sans-serif; padding: 10px; background: #fff; color: #2d3748; }}
            .btn-action {{ padding: 10px 20px; color: white; background: #2b6cb0; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; margin-bottom: 15px; }}
            .preview-card {{ background: #fff; padding: 30px; border-radius: 10px; border: 1px solid #cbd5e0; max-height: 500px; overflow-y: auto; line-height: 1.8; }}
        </style>
    </head>
    <body>
        <button class="btn-action" onclick="copyContentToClipboard_{unique_key}()">📋 Sao chép nhanh [{ai_label}] (Dán vào Word)</button>
        <div class="preview-card" id="content-to-copy_{unique_key}"></div>
        <script>
        document.getElementById('content-to-copy_{unique_key}').innerHTML = marked.parse({json.dumps(processed_html)});
        setTimeout(() => {{
            renderMathInElement(document.getElementById('content-to-copy_{unique_key}'), {{
                delimiters: [{{left: '$$', right: '$$', display: true}}, {{left: '$', right: '$', display: false}}],
                throwOnError: false
            }});
        }}, 300);
        function copyContentToClipboard_{unique_key}() {{
            const range = document.createRange();
            range.selectNode(document.getElementById('content-to-copy_{unique_key}'));
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
    components.html(preview_component_html, height=600, scrolling=False)


# --- 5. GIAO DIỆN CHÍNH (2 TABS) ---
st.title("⚡ p2w.py - Nền tảng Chuyển đổi & Xử lý Tài liệu Đa AI")

tab1, tab2 = st.tabs([
    "🚀 Tab 1: Xử lý AI Pipeline (4 Khung Preview Độc Lập)", 
    "📦 Tab 2: Quản lý & Dựng Word từ ZIP, JSON, Markdown và Ảnh"
])

# ==========================================
# TAB 1: XỬ LÝ AI PIPELINE (MISTRAL, DOCLING, MINERU, GEMINI)
# ==========================================
with tab1:
    st.subheader("🔑 Quản lý API Keys (Nhập, Đổi và Lưu an toàn)")
    
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        # Mistral Key
        m_key = st.text_input("Mistral API Key (Chính):", value=st.session_state.saved_mistral_key, type="password", disabled=not st.session_state.mistral_key_editable)
        col_mk1, col_mk2 = st.columns(2)
        with col_mk1:
            if st.button("Đổi Mistral Key", key="btn_edit_mistral"):
                st.session_state.mistral_key_editable = True
                st.rerun()
        with col_mk2:
            if st.session_state.mistral_key_editable and st.button("Lưu Mistral Key", key="btn_save_mistral"):
                st.session_state.saved_mistral_key = m_key
                save_config(st.session_state.saved_mistral_key, st.session_state.saved_docling_key, st.session_state.saved_mineru_key, st.session_state.saved_gemini_key)
                st.session_state.mistral_key_editable = False
                st.success("Đã lưu Mistral Key!")
                st.rerun()

        # Docling Key
        d_key = st.text_input("Docling API Key (Tham khảo https://developer.dcls.saas.ibm.com/):", value=st.session_state.saved_docling_key, type="password", disabled=not st.session_state.docling_key_editable)
        col_dk1, col_dk2 = st.columns(2)
        with col_dk1:
            if st.button("Đổi Docling Key", key="btn_edit_docling"):
                st.session_state.docling_key_editable = True
                st.rerun()
        with col_dk2:
            if st.session_state.docling_key_editable and st.button("Lưu Docling Key", key="btn_save_docling"):
                st.session_state.saved_docling_key = d_key
                save_config(st.session_state.saved_mistral_key, st.session_state.saved_docling_key, st.session_state.saved_mineru_key, st.session_state.saved_gemini_key)
                st.session_state.docling_key_editable = False
                st.success("Đã lưu Docling Key!")
                st.rerun()

    with col_k2:
        # MinerU Key
        mi_key = st.text_input("MinerU API Key:", value=st.session_state.saved_mineru_key, type="password", disabled=not st.session_state.mineru_key_editable)
        col_mik1, col_mik2 = st.columns(2)
        with col_mik1:
            if st.button("Đổi MinerU Key", key="btn_edit_mineru"):
                st.session_state.mineru_key_editable = True
                st.rerun()
        with col_mik2:
            if st.session_state.mineru_key_editable and st.button("Lưu MinerU Key", key="btn_save_mineru"):
                st.session_state.saved_mineru_key = mi_key
                save_config(st.session_state.saved_mistral_key, st.session_state.saved_docling_key, st.session_state.saved_mineru_key, st.session_state.saved_gemini_key)
                st.session_state.mineru_key_editable = False
                st.success("Đã lưu MinerU Key!")
                st.rerun()

        # Gemini Key
        g_key = st.text_input("Gemini Pro API Key:", value=st.session_state.saved_gemini_key, type="password", disabled=not st.session_state.gemini_key_editable)
        col_gk1, col_gk2 = st.columns(2)
        with col_gk1:
            if st.button("Đổi Gemini Key", key="btn_edit_gemini"):
                st.session_state.gemini_key_editable = True
                st.rerun()
        with col_gk2:
            if st.session_state.gemini_key_editable and st.button("Lưu Gemini Key", key="btn_save_gemini"):
                st.session_state.saved_gemini_key = g_key
                save_config(st.session_state.saved_mistral_key, st.session_state.saved_docling_key, st.session_state.saved_mineru_key, st.session_state.saved_gemini_key)
                st.session_state.gemini_key_editable = False
                st.success("Đã lưu Gemini Key!")
                st.rerun()

    st.divider()
    st.subheader("📤 Tải lên tài liệu để xử lý qua Hệ thống 4 AI song song/tuần tự")
    pipeline_file = st.file_uploader("Chọn file tài liệu (PDF, Ảnh)", type=["pdf", "png", "jpg", "jpeg"], key="tab1_file_upload")
    selected_gemini_model = st.selectbox("Chọn Model Gemini cụ thể:", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"], index=0)

    if st.button("🚀 Chạy Tất Cả 4 AI Pipeline", type="primary"):
        if not pipeline_file:
            st.warning("Vui lòng tải lên file tài liệu!")
        else:
            base_name = pipeline_file.name.rsplit(".", 1)[0]
            st.session_state.active_file_name = base_name
            
            ai_tasks = [
                ("Mistral", st.session_state.saved_mistral_key, process_with_mistral_api),
                ("Docling", st.session_state.saved_docling_key, process_with_docling_api),
                ("MinerU", st.session_state.saved_mineru_key, process_with_mineru_api),
                ("Gemini Pro", st.session_state.saved_gemini_key, lambda f, k: process_with_gemini_api(f, k, selected_gemini_model))
            ]

            for ai_name, key_val, func in ai_tasks:
                with st.spinner(f"Đang xử lý tài liệu qua mô hình: {ai_name}..."):
                    try:
                        log_info(f"Thực thi trích xuất qua {ai_name}")
                        md_res, img_res = func(pipeline_file, key_val)
                        st.session_state.ai_results[ai_name]["md"] = md_res
                        st.session_state.ai_results[ai_name]["imgs"] = img_res
                        st.success(f"✅ {ai_name} hoàn thành trích xuất!")
                    except Exception as e:
                        err_msg = f"Lỗi xử lý qua {ai_name}: {str(e)}"
                        log_error(err_msg)
                        st.session_state.ai_results[ai_name]["md"] = f"# Lỗi trích xuất từ {ai_name}\n\n> {err_msg}"
                        st.session_state.ai_results[ai_name]["imgs"] = {}
                        st.warning(err_msg)

            st.success("🎉 Đã hoàn tất chuỗi xử lý AI Pipeline!")
            st.rerun()

    # HIỂN THỊ 4 KHUNG PREVIEW ĐỘC LẬP TƯƠNG TỨNG VỚI 4 AI
    if any(res["md"] for res in st.session_state.ai_results.values()):
        st.divider()
        st.subheader("📊 Kết quả so sánh & Khung Preview độc lập của 4 AI")
        
        tab_m, tab_d, tab_mi, tab_g = st.tabs(["🌪️ Mistral OCR", "📄 Docling", "📐 MinerU", "✨ Gemini Pro"])
        
        with tab_m:
            render_preview_and_download_options(
                st.session_state.ai_results["Mistral"]["md"], 
                st.session_state.ai_results["Mistral"]["imgs"], 
                st.session_state.active_file_name, 
                "Mistral"
            )
        with tab_d:
            render_preview_and_download_options(
                st.session_state.ai_results["Docling"]["md"], 
                st.session_state.ai_results["Docling"]["imgs"], 
                st.session_state.active_file_name, 
                "Docling"
            )
        with tab_mi:
            render_preview_and_download_options(
                st.session_state.ai_results["MinerU"]["md"], 
                st.session_state.ai_results["MinerU"]["imgs"], 
                st.session_state.active_file_name, 
                "MinerU"
            )
        with tab_g:
            render_preview_and_download_options(
                st.session_state.ai_results["Gemini Pro"]["md"], 
                st.session_state.ai_results["Gemini Pro"]["imgs"], 
                st.session_state.active_file_name, 
                "Gemini Pro"
            )


# ==========================================
# TAB 2: QUẢN LÝ & DỰNG WORD TỪ ZIP, JSON, MD VÀ ẢNH
# ==========================================
with tab2:
    st.subheader("📦 Quản lý file đầu vào: ZIP, JSON, Markdown và Ảnh")
    st.write("Tải lên các gói file hoặc tệp ảnh riêng lẻ để dựng file Word và xem trước.")
    
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
                with zipfile.ZipFile(io.BytesIO(package_file.getvalue())) as z:
                    for name in z.namelist():
                        if name.endswith(".md"):
                            st.session_state.active_preview_markdown = z.read(name).decode("utf-8")
                            break
                st.session_state.active_images_dict = tab2_imgs_dict
                st.session_state.active_file_name = file_base
                st.success("Đã nạp gói ZIP thành công!")
                st.rerun()
            elif file_ext == "json":
                json_content = json.loads(package_file.getvalue().decode("utf-8"))
                st.session_state.active_images_dict = tab2_imgs_dict
                st.session_state.active_file_name = file_base
                st.session_state.active_preview_markdown = f"# Dữ liệu JSON: {file_base}\n\n```json\n" + json.dumps(json_content, ensure_ascii=False, indent=2) + "\n```"
                st.success("Đã nạp file JSON thành công!")
                st.rerun()
            elif file_ext in ["md", "markdown"]:
                st.session_state.active_preview_markdown = package_file.getvalue().decode("utf-8")
                st.session_state.active_images_dict = tab2_imgs_dict
                st.session_state.active_file_name = file_base
                st.success("Đã nạp file Markdown thành công!")
                st.rerun()
        except Exception as e:
            log_error(f"Lỗi khi xử lý file tải lên ở Tab 2: {e}")
            st.error(f"Lỗi khi đọc file: {e}")

    if st.session_state.active_preview_markdown:
        st.divider()
        render_preview_and_download_options(
            st.session_state.active_preview_markdown, 
            st.session_state.active_images_dict, 
            st.session_state.active_file_name,
            "Quản lý Workspace"
        )

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