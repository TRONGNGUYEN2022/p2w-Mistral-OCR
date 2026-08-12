import base64
import io
import json
import os
import re
import zipfile
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
LOG_FILE = os.path.join(LOG_DIR, "mistral_app.log")

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

# Import thư viện mistralai SDK[cite: 1]
try:
    from mistralai.client import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

# --- CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="Mistral OCR to Word (Extended)", page_icon="🌪️", layout="wide")

# --- HÀM ĐỌC / LƯU DANH SÁCH API KEY TỪ FILE Mistral_api_key.txt ---
KEY_FILE = "Mistral_api_key.txt"

def load_api_keys_from_file():
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                keys = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
                if keys:
                    return keys
        except Exception as e:
            log_error(f"Lỗi đọc file {KEY_FILE}: {e}")
    # Trả về key mặc định từ code gốc nếu file chưa có[cite: 1]
    return ["Asht2uDLjH8WTWnU06dBWdPbpcVQrbt5"]

def save_api_keys_to_file(keys_list):
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(keys_list))
    except Exception as e:
        log_error(f"Lỗi ghi file {KEY_FILE}: {e}")

# --- KHỞI TẠO SESSION STATE ---
if "mistral_key_editable" not in st.session_state:
    st.session_state.mistral_key_editable = False

available_keys = load_api_keys_from_file()
if "selected_mistral_key" not in st.session_state:
    st.session_state.selected_mistral_key = available_keys[0]

if "mistral_preview_markdown" not in st.session_state:
    st.session_state.mistral_preview_markdown = ""
if "mistral_docx_bytes" not in st.session_state:
    st.session_state.mistral_docx_bytes = None
if "mistral_raw_zip_bytes" not in st.session_state:
    st.session_state.mistral_raw_zip_bytes = None
if "active_images_dict" not in st.session_state:
    st.session_state.active_images_dict = {}
if "active_file_name" not in st.session_state:
    st.session_state.active_file_name = "Document"
if "mistral_json_records" not in st.session_state:
    st.session_state.mistral_json_records = []

# --- HÀM XỬ LÝ PHỤ TRỢ ---
def cleanup_old_temp_files():
    root_dir = "."
    for f_name in os.listdir(root_dir):
        if f_name.lower().endswith((".jpeg", ".jpg", ".png", ".docx", ".zip")) or f_name == "temp_input.md":
            try:
                os.remove(os.path.join(root_dir, f_name))
            except:
                pass

# --- GIAO DIỆN CHÍNH ---
st.title("🌪️ Mistral OCR to Word Converter")

st.subheader("1. Cấu hình API Key Mistral")

# Hàng chứa thông tin và nút Get API key nhanh
col_link1, col_link2 = st.columns([3, 1])
with col_link1:
    st.markdown("💡 *Chọn key từ danh sách bên dưới hoặc chỉnh sửa/lưu trực tiếp vào file `Mistral_api_key.txt`.*")
with col_link2:
    st.markdown("[🔗 Get API Key](https://console.mistral.ai/)", unsafe_allow_html=True)

# 1) Ô nhập dạng list chọn key từ file Mistral_api_key.txt
current_keys = load_api_keys_from_file()
selected_key_from_list = st.selectbox(
    "Chọn Mistral API Key từ danh sách:",
    options=current_keys,
    index=current_keys.index(st.session_state.selected_mistral_key) if st.session_state.selected_mistral_key in current_keys else 0,
    disabled=st.session_state.mistral_key_editable
)
st.session_state.selected_mistral_key = selected_key_from_list

new_key_input = st.text_input(
    "Chỉnh sửa hoặc nhập API Key mới:",
    value=st.session_state.selected_mistral_key,
    type="password",
    disabled=not st.session_state.mistral_key_editable
)

col_b1, col_b2 = st.columns(2)
with col_b1:
    if st.button("✏️ Đổi / Bật sửa Key"):
        st.session_state.mistral_key_editable = not st.session_state.mistral_key_editable
        st.rerun()
with col_b2:
    if st.session_state.mistral_key_editable and st.button("💾 Lưu Key vào danh sách"):
        cleaned_key = new_key_input.strip()
        if cleaned_key and cleaned_key not in current_keys:
            current_keys.append(cleaned_key)
            save_api_keys_to_file(current_keys)
        st.session_state.selected_mistral_key = cleaned_key
        st.session_state.mistral_key_editable = False
        st.success("Đã lưu API Key thành công!")
        log_info("Đã cập nhật Mistral API Key mới.")
        st.rerun()

st.divider()

# 2) Nút upload file PDF, Images
st.subheader("2. Tải lên tài liệu (PDF hoặc Ảnh)")
mistral_file = st.file_uploader(
    "Chọn file PDF hoặc hình ảnh (PNG, JPG, JPEG) để xử lý OCR", 
    type=["pdf", "png", "jpg", "jpeg"], 
    key="mistral_upload"
)

# 3) Nút gửi server Mistral phân tích xử lý
if st.button("🚀 Gửi server Mistral phân tích xử lý"):
    active_m_key = st.session_state.selected_mistral_key.strip()
    if not mistral_file:
        st.warning("Vui lòng chọn file!")
    elif not active_m_key:
        st.error("Vui lòng nhập hoặc chọn Mistral API Key!")
    elif not MISTRAL_AVAILABLE:
        st.error("Chưa cài đặt thư viện `mistralai`[cite: 1].")
    else:
        cleanup_old_temp_files()
        original_full_name = mistral_file.name
        base_name_only = original_full_name.rsplit('.', 1)[0]
        log_info(f"Bắt đầu xử lý Mistral OCR cho file: {original_full_name}")

        with st.spinner("Đang gửi file lên Mistral OCR API và gom dữ liệu JSON/Markdown..."):
            try:
                client = Mistral(api_key=active_m_key)
                file_bytes = mistral_file.getvalue()
                base64_file = base64.b64encode(file_bytes).decode('utf-8')

                file_extension = original_full_name.split('.')[-1].lower()
                if file_extension == 'pdf':
                    doc_payload = {"type": "document_url", "document_url": f"data:application/pdf;base64,{base64_file}"}
                else:
                    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
                    mime_type = mime_map.get(file_extension, "image/jpeg")
                    doc_payload = {"type": "image_url", "image_url": f"data:{mime_type};base64,{base64_file}"}

                ocr_response = client.ocr.process(
                    document=doc_payload,
                    model="mistral-ocr-latest",
                    include_image_base64=True,
                    include_blocks=True
                )
                
                full_markdown = ""
                images_dict = {}
                json_records = []
                
                if hasattr(ocr_response, "pages"):
                    for idx, page in enumerate(ocr_response.pages):
                        page_md = page.markdown if hasattr(page, "markdown") else ""
                        page_md = re.sub(r'!\[(.*?)\]\([^)]*?(img[_-]\d+\.(?:jpeg\vert{}jpg\vert{}png))\)', r'![\1](\2)', page_md)
                        page_md_safe = re.sub(r'^\s*---\s*$', '<hr/>', page_md, flags=re.MULTILINE)
                        
                        # Nối nội dung theo yêu cầu dựng từ các cấu trúc JSON/trang trả về
                        full_markdown += f"\n\n<hr/>\n<h3>Trang {idx+1}</h3>\n\n" + page_md_safe
                        
                        # Lưu trữ bản ghi json của từng trang/block phục vụ việc nối dữ liệu
                        page_json_data = {
                            "page_index": idx + 1,
                            "markdown": page_md,
                            "images_count": len(page.images) if hasattr(page, "images") and page.images else 0
                        }
                        json_records.append(page_json_data)
                        
                        if hasattr(page, "images") and page.images:
                            for img in page.images:
                                if hasattr(img, "id") and hasattr(img, "image_base64") and img.image_base64:
                                    img_id = img.id
                                    img_b64 = img.image_base64
                                    if "," in img_b64: img_b64 = img_b64.split(",")[1]
                                    try:
                                        img_data_decoded = base64.b64decode(img_b64)
                                        img_filename = img_id if img_id.lower().endswith((".jpeg", ".jpg", ".png")) else f"{img_id}.jpeg"
                                        images_dict[img_filename] = img_data_decoded
                                    except: 
                                        pass

                st.session_state.mistral_json_records = json_records

                # Tạo file ZIP thô chứa các dữ liệu liên quan
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.writestr("output.md", full_markdown)
                    zip_file.writestr("concatenated_records.json", json.dumps(json_records, ensure_ascii=False, indent=4))
                    for img_name, img_bytes in images_dict.items():
                        zip_file.writestr(f"images/{img_name}", img_bytes)
                st.session_state.mistral_raw_zip_bytes = zip_buffer.getvalue()

                # Chuyển đổi sang file Word bằng pypandoc[cite: 1]
                with tempfile.TemporaryDirectory() as tmp_dir:
                    temp_md_path = os.path.join(tmp_dir, "temp_input.md")
                    with open(temp_md_path, "w", encoding="utf-8") as f:
                        f.write(full_markdown)
                    
                    for img_name, img_bytes in images_dict.items():
                        with open(os.path.join(tmp_dir, img_name), "wb") as img_f:
                            img_f.write(img_bytes)
                            
                    original_dir = os.getcwd()
                    os.chdir(tmp_dir)
                    
                    try:
                        output_docx = "Mistral_Output.docx"
                        pypandoc.convert_file(
                            "temp_input.md", 
                            'docx', 
                            outputfile=output_docx, 
                            extra_args=['--standalone', '--extract-media=.']
                        )
                        with open(output_docx, "rb") as f:
                            docx_bytes = f.read()
                        st.session_state.mistral_docx_bytes = docx_bytes
                    finally:
                        os.chdir(original_dir)

                st.session_state.mistral_preview_markdown = full_markdown
                st.session_state.active_images_dict = images_dict
                st.session_state.active_file_name = base_name_only
                
                log_info("Xử lý Mistral OCR và nối JSON thành công.")
                st.success("🎉 Phân tích server Mistral OCR thành công!")
            except Exception as e:
                log_error(f"Lỗi phân tích Mistral OCR: {str(e)}")
                st.error(f"Lỗi khi xử lý: {e}")

# --- 4) KHUNG XEM TRƯỚC VÀ CÁC TÙY CHỌN TẢI XUỐNG ---
if st.session_state.mistral_preview_markdown:
    st.divider()
    current_file_name = st.session_state.get("active_file_name", "Document")
    
    st.subheader(f"4. Khung xem trước & Tùy chọn tải xuống ({current_file_name})")

    # Các nút tải xuống yêu cầu (Tải word pandoc, tải word từ khung xem trước, gói zip)
    col_dl1, col_dl2, col_dl3 = st.columns(3)
    
    with col_dl1:
        if st.session_state.mistral_docx_bytes:
            st.download_button(
                label="📥 Tải Word (Pandoc .docx)",
                data=st.session_state.mistral_docx_bytes,
                file_name=f"{current_file_name}_pandoc.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )
            
    with col_dl2:
        if st.session_state.mistral_docx_bytes:
            st.download_button(
                label="📥 Tải Word (Từ khung xem trước)",
                data=st.session_state.mistral_docx_bytes,
                file_name=f"{current_file_name}_preview.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )

    with col_dl3:
        if st.session_state.get("mistral_raw_zip_bytes"):
            st.download_button(
                label="📦 Tải file ZIP thô (JSON + MD + Ảnh)",
                data=st.session_state.mistral_raw_zip_bytes,
                file_name=f"{current_file_name}_Raw.zip",
                mime="application/zip",
                use_container_width=True
            )

    raw_md = st.session_state.mistral_preview_markdown
    
    def replace_img_smart_html(match):
        alt_text = match.group(1)
        raw_path = match.group(2)
        target_name = os.path.basename(raw_path)
        matched_bytes = None
        for k, v in st.session_state.active_images_dict.items():
            if target_name in k or k in target_name:
                matched_bytes = v
                break
        if matched_bytes:
            b64_data = base64.b64encode(matched_bytes).decode('utf-8')
            return f'<div style="text-align: center; margin: 20px 0;"><img src="data:image/jpeg;base64,{b64_data}" style="max-width: 450px; border-radius: 8px; border: 1px solid #2d3748;" alt="{alt_text}" /></div>'
        return match.group(0)

    processed_html = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_img_smart_html, raw_md)
    escaped_markdown_json = json.dumps(processed_html)

    # Component giao diện xem trước kèm nút Copy dán Word trực tiếp
    mistral_component_html = f"""
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
    components.html(mistral_component_html, height=780, scrolling=False)