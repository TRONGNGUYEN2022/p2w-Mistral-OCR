import base64
import io
import json
import os
import re
import zipfile
import tempfile
import logging
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

# Import thư viện mistralai SDK
try:
    from mistralai.client import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

# Import thư viện google-genai chính thức mới nhất cho bước chuẩn hóa tiếng Việt
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# --- CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="Universal OCR & AI Vietnamese Normalizer to Word", page_icon="🌪️", layout="wide")

# --- HÀM ĐỌC / LƯU DANH SÁCH API KEY TỪ FILE ---
KEY_FILE = "Mistral_api_key.txt"
CONFIG_FILE = "config_keys.json"

def load_api_keys_from_file():
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                keys = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
                if keys:
                    return keys
        except Exception as e:
            log_error(f"Lỗi đọc file {KEY_FILE}: {e}")
    return ["Asht2uDLjH8WTWnU06dBWdPbpcVQrbt5"] # Key mặc định dự phòng

def save_api_keys_to_file(keys_list):
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(keys_list))
    except Exception as e:
        log_error(f"Lỗi ghi file {KEY_FILE}: {e}")

def load_saved_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_config(gemini_key):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"gemini_key": gemini_key}, f, ensure_ascii=False, indent=4)
    except:
        pass

saved_config = load_saved_config()
DEFAULT_GEMINI_KEY = saved_config.get("gemini_key", "")

# --- KHỞI TẠO SESSION STATE ---
if "mistral_key_editable" not in st.session_state:
    st.session_state.mistral_key_editable = False
if "gemini_key_editable" not in st.session_state:
    st.session_state.gemini_key_editable = False
if "saved_gemini_key" not in st.session_state:
    st.session_state.saved_gemini_key = DEFAULT_GEMINI_KEY

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

def extract_images_from_json_obj(j_obj, images_dict):
    """Bóc tách ảnh base64 trực tiếp nằm trong cấu trúc JSON OCR bất kỳ"""
    def search_and_extract(data):
        if isinstance(data, dict):
            if "images" in data and isinstance(data["images"], list):
                for img_item in data["images"]:
                    if isinstance(img_item, dict):
                        img_id = img_item.get("id") or img_item.get("name")
                        b64_str = img_item.get("image_base64") or img_item.get("base64") or img_item.get("data")
                        if img_id and b64_str:
                            if "," in b64_str:
                                b64_str = b64_str.split(",")[1]
                            try:
                                images_dict[img_id] = base64.b64decode(b64_str)
                            except Exception as e:
                                log_error(f"Lỗi giải mã base64 ảnh {img_id}: {e}")
            for v in data.values():
                search_and_extract(v)
        elif isinstance(data, list):
            for item in data:
                search_and_extract(item)

    search_and_extract(j_obj)

def normalize_vietnamese_text_with_gemini(raw_markdown, gemini_api_key, model_name="gemini-2.5-flash"):
    """Dùng Gemini AI để chuẩn hóa tiếng Việt, sửa lỗi chính tả OCR và định dạng LaTeX toán học"""
    if not GEMINI_AVAILABLE or not gemini_api_key.strip():
        log_info("Bỏ qua bước chuẩn hóa Gemini do thiếu thư viện hoặc API Key.")
        return raw_markdown
    
    try:
        client = genai.Client(api_key=gemini_api_key.strip())
        system_instruction = (
            "Bạn là chuyên gia biên tập tài liệu, chuyên gia xử lý OCR và định dạng văn bản học thuật (tiếng Việt và toán học). "
            "Nhiệm vụ của bạn là làm sạch và chuẩn hóa lại nội dung Markdown được cung cấp từ kết quả OCR thô:\n"
            "1. Sửa toàn bộ lỗi chính tả tiếng Việt bị sai do OCR (mất dấu, dính chữ, sai dấu thanh, nhận diện sai ký tự).\n"
            "2. Chuẩn hóa cấu trúc: Gộp các dòng bị ngắt cụt cụn lủn thành đoạn văn hoàn chỉnh, giữ đúng định dạng tiêu đề (#, ##).\n"
            "3. Chuẩn hóa công thức toán học: Mọi biểu thức toán học, ký hiệu, phân số PHẢI được bọc chuẩn trong cặp dấu đô la ($...$ cho inline hoặc $$...$$ cho block LaTeX).\n"
            "4. Giữ nguyên các cú pháp chèn ảnh Markdown (ví dụ: ![alt](path)) và cấu trúc bảng.\n"
            "5. Chỉ trả về kết quả nội dung Markdown đã được chuẩn hóa sạch sẽ, không kèm theo giải thích gì thêm."
        )

        response = client.models.generate_content(
            model=model_name,
            contents=[raw_markdown],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1
            )
        )
        cleaned_text = response.text
        cleaned_text = cleaned_text.replace("```markdown", "").replace("```", "").strip()
        log_info("Chuẩn hóa tiếng Việt bằng Gemini thành công.")
        return cleaned_text
    except Exception as e:
        log_error(f"Lỗi khi chuẩn hóa bằng Gemini: {e}")
        return raw_markdown

def compile_markdown_to_word(full_markdown, images_dict):
    """Biên dịch Markdown + Ảnh thành file Word (.docx) và ZIP thô"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("output.md", full_markdown)
        for img_name, img_bytes in images_dict.items():
            zip_file.writestr(f"images/{img_name}", img_bytes)
            zip_file.writestr(f"{img_name}", img_bytes)
    st.session_state.mistral_raw_zip_bytes = zip_buffer.getvalue()

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_md_path = os.path.join(tmp_dir, "temp_input.md")
        img_sub_dir = os.path.join(tmp_dir, "images")
        os.makedirs(img_sub_dir, exist_ok=True)
        
        for img_name, img_bytes in images_dict.items():
            clean_name = os.path.basename(img_name)
            with open(os.path.join(tmp_dir, clean_name), "wb") as f_root:
                f_root.write(img_bytes)
            with open(os.path.join(img_sub_dir, clean_name), "wb") as f_sub:
                f_sub.write(img_bytes)

        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(full_markdown)
                
        original_dir = os.getcwd()
        os.chdir(tmp_dir)
        
        try:
            output_docx = "Output_Document.docx"
            pypandoc.convert_file(
                "temp_input.md", 
                'docx', 
                outputfile=output_docx, 
                extra_args=['--standalone', '--resource-path=.:images']
            )
            with open(output_docx, "rb") as f:
                docx_bytes = f.read()
            st.session_state.mistral_docx_bytes = docx_bytes
        except Exception as e:
            log_error(f"Lỗi khi pypandoc biên dịch ra docx: {e}")
        finally:
            os.chdir(original_dir)

# --- GIAO DIỆN CHÍNH (2 TABS) ---
st.title("🌪️ Universal OCR & AI Text Normalizer to Word")

tab_online, tab_offline = st.tabs(["🚀 Mistral OCR (Online)", "📁 Xử lý Offline (ZIP, JSON, Markdown + AI Fix Tiếng Việt)"])

# ==========================================
# TAB 1: MISTRAL OCR ONLINE
# ==========================================
with tab_online:
    st.subheader("1. Cấu hình API Key Mistral")

    col_link1, col_link2 = st.columns([3, 1])
    with col_link1:
        st.markdown("💡 *Chọn key từ danh sách bên dưới hoặc chỉnh sửa/lưu trực tiếp vào file `Mistral_api_key.txt`.*")
    with col_link2:
        st.markdown("[🔗 Get API Key](https://console.mistral.ai/)", unsafe_allow_html=True)

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

    st.subheader("2. Tải lên tài liệu (PDF hoặc Ảnh)")
    mistral_file = st.file_uploader(
        "Chọn file PDF hoặc hình ảnh (PNG, JPG, JPEG) để xử lý OCR", 
        type=["pdf", "png", "jpg", "jpeg"], 
        key="mistral_upload"
    )

    if st.button("🚀 Gửi server Mistral phân tích xử lý"):
        active_m_key = st.session_state.selected_mistral_key.strip()
        if not mistral_file:
            st.warning("Vui lòng chọn file!")
        elif not active_m_key:
            st.error("Vui lòng nhập hoặc chọn Mistral API Key!")
        elif not MISTRAL_AVAILABLE:
            st.error("Chưa cài đặt thư viện `mistralai`.")
        else:
            cleanup_old_temp_files()
            original_full_name = mistral_file.name
            base_name_only = original_full_name.rsplit('.', 1)[0]
            log_info(f"Bắt đầu xử lý Mistral OCR cho file: {original_full_name}")

            with st.spinner("Đang gửi file lên Mistral OCR API và gom dữ liệu..."):
                try:
                    client = Mistral(api_key=active_m_key)
                    file_bytes = mistral_file.getvalue()
                    base64_file = base64.b64encode(file_bytes).decode('utf-8')

                    file_ext = original_full_name.split('.')[-1].lower()
                    if file_ext == 'pdf':
                        doc_payload = {"type": "document_url", "document_url": f"data:application/pdf;base64,{base64_file}"}
                    else:
                        mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
                        mime_type = mime_map.get(file_ext, "image/jpeg")
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
                            page_md = re.sub(r'!\[(.*?)\]\([^)]*?(img[_-]\d+\.(?:jpeg|jpg|png))\)', r'![\1](\2)', page_md)
                            page_md_safe = re.sub(r'^\s*---\s*$', '<hr/>', page_md, flags=re.MULTILINE)
                            
                            full_markdown += f"\n\n<hr/>\n<h3>Trang {idx+1}</h3>\n\n" + page_md_safe
                            
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
                    st.session_state.mistral_preview_markdown = full_markdown
                    st.session_state.active_images_dict = images_dict
                    st.session_state.active_file_name = base_name_only

                    compile_markdown_to_word(full_markdown, images_dict)
                    log_info("Xử lý Mistral OCR thành công.")
                    st.success("🎉 Phân tích server Mistral OCR thành công!")
                except Exception as e:
                    log_error(f"Lỗi phân tích Mistral OCR: {str(e)}")
                    st.error(f"Lỗi khi xử lý: {e}")

# ==========================================
# TAB 2: XỬ LÝ OFFLINE (ZIP, JSON, MD + AI FIX TIẾNG VIỆT)
# ==========================================
with tab_offline:
    st.subheader("📁 Nạp, Chuẩn hóa Tiếng Việt bằng AI & Dựng Word Offline")
    st.markdown("💡 *Upload bất kỳ file JSON, Markdown, ZIP nào và cung cấp Gemini API Key để AI tự động sửa lỗi tiếng Việt, chuẩn hóa LaTeX rồi đóng gói ra Word.*")
    
    col_gk1, col_gk2 = st.columns(2)
    with col_gk1:
        def update_gemini_key():
            st.session_state.saved_gemini_key = st.session_state.gemini_input_field
            save_config(st.session_state.saved_gemini_key)

        gemini_token_input = st.text_input(
            "Nhập Gemini API Key (để AI fix lỗi tiếng Việt):", 
            value=st.session_state.saved_gemini_key, 
            type="password", 
            disabled=not st.session_state.gemini_key_editable, 
            key="gemini_input_field", 
            on_change=update_gemini_key
        )
        if st.button("Đổi Gemini Key"):
            st.session_state.gemini_key_editable = not st.session_state.gemini_key_editable
            st.rerun()
        if st.session_state.gemini_key_editable and st.button("Lưu Gemini Key"):
            st.session_state.saved_gemini_key = gemini_token_input
            save_config(st.session_state.saved_gemini_key)
            st.session_state.gemini_key_editable = False
            st.success("Đã lưu Gemini Key!")
            st.rerun()
    with col_gk2:
        selected_gemini_model = st.selectbox("Chọn Model Gemini chuẩn hóa:", ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"], index=0)

    offline_file = st.file_uploader(
        "Chọn file cấu trúc chính (ZIP, JSON hoặc Markdown)", 
        type=["zip", "json", "md"], 
        key="offline_upload_tab"
    )
    
    extra_image_files = st.file_uploader(
        "Chọn các file ảnh bổ sung rời (PNG, JPG, JPEG - tùy chọn)", 
        type=["png", "jpg", "jpeg"], 
        accept_multiple_files=True, 
        key="offline_extra_imgs"
    )
    
    use_ai_normalization = st.checkbox("✨ Sử dụng AI (Gemini) để sửa lỗi chính tả tiếng Việt & chuẩn hóa LaTeX", value=True)

    if st.button("⚙️ Xử lý, Chuẩn hóa AI & Dựng file Word"):
        if not offline_file:
            st.warning("Vui lòng tải lên file dữ liệu cấu trúc chính!")
        else:
            cleanup_old_temp_files()
            file_name_full = offline_file.name
            base_name_off = file_name_full.rsplit('.', 1)[0]
            file_extension = file_name_full.split('.')[-1].lower()

            full_markdown = ""
            images_dict = {}
            json_records = []

            try:
                file_bytes = offline_file.getvalue()
                
                # 1. Nạp và bóc tách từ file ZIP
                if file_extension == "zip":
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                        for filename in z.namelist():
                            if ("images/" in filename or filename.lower().endswith((".png", ".jpg", ".jpeg"))) and not filename.endswith("/"):
                                img_name = os.path.basename(filename)
                                images_dict[img_name] = z.read(filename)
                            elif filename.endswith(".json") and not filename.startswith("__MACOSX"):
                                try:
                                    j_content = json.loads(z.read(filename).decode("utf-8"))
                                    json_records.append({"filename": filename, "data": j_content})
                                    extract_images_from_json_obj(j_content, images_dict)
                                    
                                    if "pages" in j_content:
                                        for p_idx, page in enumerate(j_content["pages"]):
                                            p_md = page.get("markdown", "")
                                            full_markdown += f"\n\n<h3>Trang {p_idx+1}</h3>\n\n" + p_md
                                    elif "ketQuaOcr" in j_content and "pages" in j_content["ketQuaOcr"]:
                                        for p_obj in j_content["ketQuaOcr"]["pages"]:
                                            p_idx = p_obj.get("index", 0)
                                            p_md = p_obj.get("markdown", "")
                                            full_markdown += f"\n\n<h3>Trang {p_idx+1}</h3>\n\n" + p_md
                                    elif "pdf_info" in j_content:
                                        full_markdown += f"\n\n" + json.dumps(j_content, ensure_ascii=False, indent=2)
                                    else:
                                        full_markdown += f"\n\n<!-- File: {filename} -->\n" + json.dumps(j_content, ensure_ascii=False, indent=2)
                                except Exception as e:
                                    log_error(f"Lỗi đọc file json trong zip: {e}")
                            elif filename.endswith(".md") and not filename.startswith("__MACOSX"):
                                md_content = z.read(filename).decode("utf-8")
                                full_markdown += f"\n\n<!-- File: {filename} -->\n" + md_content

                # 2. Nạp từ file JSON đơn lẻ bất kỳ (như 123_ocr_raw.json hoặc Docling JSON)
                elif file_extension == "json":
                    j_content = json.loads(file_bytes.decode("utf-8"))
                    json_records.append({"filename": file_name_full, "data": j_content})
                    extract_images_from_json_obj(j_content, images_dict)
                    
                    if "pages" in j_content:
                        for p_idx, page in enumerate(j_content["pages"]):
                            p_md = page.get("markdown", "")
                            full_markdown += f"\n\n<h3>Trang {p_idx+1}</h3>\n\n" + p_md
                    elif "ketQuaOcr" in j_content and "pages" in j_content["ketQuaOcr"]:
                        for p_obj in j_content["ketQuaOcr"]["pages"]:
                            p_idx = p_obj.get("index", 0)
                            p_md = p_obj.get("markdown", "")
                            full_markdown += f"\n\n<h3>Trang {p_idx+1}</h3>\n\n" + p_md
                    elif "pdf_info" in j_content:
                        full_markdown = json.dumps(j_content, ensure_ascii=False, indent=2)
                    else:
                        full_markdown = json.dumps(j_content, ensure_ascii=False, indent=2)

                # 3. Nạp từ file Markdown đơn lẻ (.md)
                elif file_extension == "md":
                    full_markdown = file_bytes.decode("utf-8")

                # 4. Gộp ảnh rời từ giao diện
                if extra_image_files:
                    for img_item in extra_image_files:
                        images_dict[img_item.name] = img_item.getvalue()

                # Bước chuẩn hóa bằng AI (Gemini) nếu được bật
                if use_ai_normalization:
                    active_g_key = st.session_state.saved_gemini_key.strip()
                    if active_g_key and GEMINI_AVAILABLE:
                        with st.spinner("Đang dùng Gemini AI chuẩn hóa chính tả tiếng Việt và LaTeX..."):
                            full_markdown = normalize_vietnamese_text_with_gemini(full_markdown, active_g_key, selected_gemini_model)
                    else:
                        st.warning("Chưa có Gemini API Key nên không thể thực hiện chuẩn hóa AI! Tiến hành xử lý cấu trúc thô...")

                st.session_state.mistral_json_records = json_records
                st.session_state.mistral_preview_markdown = full_markdown
                st.session_state.active_images_dict = images_dict
                st.session_state.active_file_name = base_name_off

                # Biên dịch ra file Word
                compile_markdown_to_word(full_markdown, images_dict)
                st.success(f"🎉 Xử lý thành công! Đã chuẩn hóa, bóc tách {len(images_dict)} ảnh và tạo xong file Word!")
            except Exception as e:
                log_error(f"Lỗi xử lý file offline: {str(e)}")
                st.error(f"Lỗi khi xử lý file: {e}")

# ==========================================
# KHUNG XEM TRƯỚC VÀ TẢI XUỐNG DÙNG CHUNG
# ==========================================
if st.session_state.mistral_preview_markdown:
    st.divider()
    current_file_name = st.session_state.get("active_file_name", "Document")
    
    st.subheader(f"👁️ Khung xem trước kết quả: {current_file_name}")

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