import base64
import io
import json
import os
import re
import zipfile
import tempfile
import logging
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
st.set_page_config(page_title="Mistral OCR & Client-Side ZIP Processor", page_icon="🌪️", layout="wide")

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
    return ["Asht2uDLjH8WTWnU06dBWdPbpcVQrbt5"] # Key mặc định dự phòng[cite: 1]

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

def compile_markdown_to_word(full_markdown, images_dict):
    """Hàm chuyển đổi Markdown + Ảnh sang file Word (.docx) tối ưu bộ nhớ tạm"""
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
st.title("🌪️ Mistral OCR & Client-Side ZIP Preprocessor")

tab_online, tab_offline = st.tabs(["🚀 Mistral OCR (Online)", "📁 Xử lý Offline (Client-side ZIP Flattening)"])

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
            st.error("Vui lòng nhập hoặc chọn Mistral API Key!")[cite: 1]
        elif not MISTRAL_AVAILABLE:
            st.error("Chưa cài đặt thư viện `mistralai`.")[cite: 1]
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
# TAB 2: XỬ LÝ OFFLINE (GỘP ZIP TẠI TRÌNH DUYỆT BẰNG JS)
# ==========================================
with tab_offline:
    st.subheader("📁 Xử lý Offline Siêu Tốc (Xử lý ZIP ngay tại trình duyệt máy khách)")
    st.markdown("💡 *Sử dụng thư viện JavaScript chạy trực tiếp trên trình duyệt của bạn để giải nén ZIP, gom toàn bộ ảnh từ các thư mục con ra ngoài, gộp tất cả file JSON thành 1 file gọn nhẹ duy nhất rồi mới truyền lên server, loại bỏ hoàn toàn hiện tượng tràn RAM.*")

    # Sử dụng HTML/JS Component để xử lý gói ZIP ngay tại Client-side trước khi truyền vào st.file_uploader hoặc form
    client_zip_component = """
    <div>
        <label style="font-weight: bold; color: #2d3748; font-size: 14px;">Chọn file ZIP tài liệu lớn:</label><br/>
        <input type="file" id="zipFileInput" accept=".zip" style="margin: 10px 0; padding: 5px; border: 1px solid #cbd5e0; border-radius: 4px; width: 100%; background: #f7fafc;" />
        <div id="processingStatus" style="font-weight: bold; color: #2b6cb0; margin-top: 5px; font-size: 13px;"></div>
    </div>
    
    <!-- Tích hợp thư viện JSZip từ CDN -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
    <script>
    document.getElementById('zipFileInput').addEventListener('change', async function(e) {
        const file = e.target.files[0];
        if (!file) return;
        
        const statusDiv = document.getElementById('processingStatus');
        statusDiv.innerText = "Đang xử lý giải nén và gom file tại máy khách (Client-side)...";
        
        try {
            const zip = new Zip();
            const content = await zip.loadAsync(file);
            
            let allJsonData = [];
            let imagesMap = {};
            
            // Duyệt qua tất cả các file bên trong ZIP bất kể thư mục con
            let fileEntries = Object.keys(content.files);
            for (let filename of fileEntries) {
                let zipEntry = content.files[filename];
                if (zipEntry.dir || filename.includes('__MACOSX')) continue;
                
                let baseName = filename.split('/').pop();
                if (!baseName) continue;
                
                // Nếu là file JSON
                if (filename.toLowerCase().endsWith('.json')) {
                    try {
                        let textContent = await zipEntry.async("text");
                        let jsonObj = JSON.parse(textContent);
                        allJsonData.push({ filename: filename, data: jsonObj });
                    } catch (err) {
                        console.log("Lỗi đọc JSON:", filename);
                    }
                }
                // Nếu là file ảnh từ bất kỳ thư mục nào
                else if (/\.(png|jpg|jpeg|webp)$/i.test(baseName)) {
                    let imgBlob = await zipEntry.async("blob");
                    imagesMap[baseName] = imgBlob;
                }
            }
            
            statusDiv.innerText = `Đã quét xong: ${allJsonData.length} file JSON và ${Object.keys(imagesMap).length} file ảnh. Đang đóng gói lại file gọn nhẹ...`;
            
            // Tạo một file ZIP mới siêu gọn (chỉ gồm 1 file gộp combined_data.json và thư mục images phẳng)
            const newZip = new JSZip();
            newZip.file("combined_data.json", JSON.stringify(allJsonData, null, 2));
            const imgFolder = newZip.folder("images");
            for (let imgName in imagesMap) {
                imgFolder.file(imgName, imagesMap[imgName]);
            }
            
            const optimizedZipBlob = await newZip.generateAsync({ type: "blob" });
            
            // Gửi dữ liệu sạch đã tối ưu về cho Streamlit thông qua window.parent
            const reader = new FileReader();
            reader.readAsDataURL(optimizedZipBlob);
            reader.onloadend = function() {
                const base64data = reader.result;
                // Truyền dữ liệu sang Streamlit qua custom component message hoặc hidden input
                const dataPayload = {
                    filename: file.name.replace(/\.[^/.]+$/, "") + "_optimized.zip",
                    payload: base64data
                };
                // Gửi sự kiện cho Streamlit
                window.parent.postMessage({ type: 'streamlit:setComponentValue', value: dataPayload }, '*');
                statusDiv.innerText = "✔ Đã tối ưu và gửi dữ liệu sạch lên server thành công!";
            }
            
        } catch (error) {
            statusDiv.innerText = "Lỗi xử lý file ZIP ở máy khách: " + error.message;
        }
    });
    </script>
    """
    
    # Hiển thị component xử lý ZIP tại client
    client_zip_result = components.html(client_zip_component, height=120)
    
    st.divider()
    st.markdown("Hoặc tải lên file JSON/Markdown đơn lẻ / Gói ZIP đã tối ưu trực tiếp bên dưới:")
    
    offline_file = st.file_uploader(
        "Chọn file cấu trúc chính (JSON, Markdown hoặc ZIP đã tối ưu)", 
        type=["zip", "json", "md"], 
        key="offline_upload_tab"
    )
    
    normalization_option = st.checkbox("✨ Kích hoạt cơ chế làm sạch & chuẩn hóa định dạng văn bản", value=True, key="off_norm")

    if st.button("⚙️ Xử lý, Nhúng ảnh & Dựng file Word Offline"):
        if not offline_file:
            st.warning("Vui lòng tải lên file dữ liệu cấu trúc chính!")
        else:
            cleanup_old_temp_files()
            file_name_full = offline_file.name
            base_name_off = file_name_full.rsplit('.', 1)[0]
            file_extension = file_name_full.split('.')[-1].lower()

            full_markdown_list = []
            images_dict = {}
            json_records = []

            try:
                file_bytes = offline_file.getvalue()
                
                # Xử lý file ZIP an toàn sau khi đã được tối ưu phẳng hóa cấu trúc ảnh và JSON
                if file_extension == "zip":
                    with tempfile.TemporaryDirectory() as tmp_extract_dir:
                        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                            z.extractall(tmp_extract_dir)
                        
                        for root, dirs, files in os.walk(tmp_extract_dir):
                            for file in files:
                                full_path = os.path.join(root, file)
                                rel_path = os.path.relpath(full_path, tmp_extract_dir)
                                
                                if "__MACOSX" in rel_path:
                                    continue
                                
                                if "images/" in rel_path.replace("\\", "/") or file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                                    with open(full_path, "rb") as img_f:
                                        images_dict[file] = img_f.read()
                                elif file.endswith(".json"):
                                    try:
                                        with open(full_path, "r", encoding="utf-8") as j_f:
                                            j_content = json.load(j_f)
                                        json_records.append({"filename": rel_path, "data": j_content})
                                        
                                        # Nếu là file gộp từ client-side, nó là mảng các record
                                        if isinstance(j_content, list):
                                            for rec in j_content:
                                                d_val = rec.get("data", rec)
                                                if isinstance(d_val, dict):
                                                    if "pages" in d_val:
                                                        for p_idx, page in enumerate(d_val["pages"]):
                                                            full_markdown_list.append(f"\n\n<h3>Trang {p_idx+1}</h3>\n\n" + page.get("markdown", ""))
                                                    elif "markdown" in d_val:
                                                        full_markdown_list.append(d_val["markdown"])
                                                    else:
                                                        full_markdown_list.append(json.dumps(d_val, ensure_ascii=False, indent=2))
                                        elif isinstance(j_content, dict):
                                            if "pages" in j_content:
                                                for p_idx, page in enumerate(j_content["pages"]):
                                                    full_markdown_list.append(f"\n\n<h3>Trang {p_idx+1}</h3>\n\n" + page.get("markdown", ""))
                                            else:
                                                full_markdown_list.append(json.dumps(j_content, ensure_ascii=False, indent=2))
                                    except Exception as e:
                                        log_error(f"Lỗi đọc JSON: {e}")
                                elif file.endswith(".md"):
                                    with open(full_path, "r", encoding="utf-8", errors="ignore") as md_f:
                                        full_markdown_list.append(md_f.read())

                # Xử lý JSON đơn lẻ
                elif file_extension == "json":
                    j_content = json.loads(file_bytes.decode("utf-8"))
                    json_records.append({"filename": file_name_full, "data": j_content})
                    if isinstance(j_content, list):
                        for rec in j_content:
                            d_val = rec.get("data", rec)
                            if isinstance(d_val, dict) and "pages" in d_val:
                                for p_idx, page in enumerate(d_val["pages"]):
                                    full_markdown_list.append(f"\n\n<h3>Trang {p_idx+1}</h3>\n\n" + page.get("markdown", ""))
                    elif isinstance(j_content, dict) and "pages" in j_content:
                        for p_idx, page in enumerate(j_content["pages"]):
                            full_markdown_list.append(f"\n\n<h3>Trang {p_idx+1}</h3>\n\n" + page.get("markdown", ""))
                    else:
                        full_markdown_list.append(json.dumps(j_content, ensure_ascii=False, indent=2))

                # Xử lý Markdown đơn lẻ
                elif file_extension == "md":
                    full_markdown_list.append(file_bytes.decode("utf-8", errors="ignore"))

                full_markdown = "".join(full_markdown_list)

                if normalization_option:
                    full_markdown = re.sub(r'\n{3,}', '\n\n', full_markdown)
                    full_markdown = full_markdown.replace("-\n", "")

                st.session_state.mistral_json_records = json_records
                st.session_state.mistral_preview_markdown = full_markdown
                st.session_state.active_images_dict = images_dict
                st.session_state.active_file_name = base_name_off

                compile_markdown_to_word(full_markdown, images_dict)
                st.success(f"🎉 Xử lý thành công! Đã nhận diện {len(images_dict)} ảnh và tạo xong file Word.")
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