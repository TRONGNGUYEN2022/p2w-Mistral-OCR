import base64
import io
import json
import os
import re
import zipfile
import tempfile
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Import thư viện mistralai SDK[cite: 1]
try:
    from mistralai.client import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

# --- CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="p2w.py - Multi-AI Concurrent & Rotation Suite", page_icon="⚡", layout="wide")
DOCLING_BASE_URL = "https://api.aws-c1.dcls.saas.ibm.com/20260811-1219-1052-8050-3cf005cc005c"
MINERU_BASE_URL = "https://mineru.net"

KEY_FILE = "api_key_Mistral.txt"

def load_mistral_keys_from_file():
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                return f.read()
        except:
            pass
    return "Asht2uDLjH8WTWnU06dBWdPbpcVQrbt5"[cite: 1]

if "saved_mistral_keys_raw" not in st.session_state:
    st.session_state.saved_mistral_keys_raw = load_mistral_keys_from_file()

if "ai_results" not in st.session_state:
    st.session_state.ai_results = {
        "Mistral": {"json": None, "md": "", "imgs": {}, "name": "Document"},
        "Offline Processor": {"json": None, "md": "", "imgs": {}, "name": "Document"}
    }

def cleanup_old_temp_files():
    root_dir = "."
    for f_name in os.listdir(root_dir):
        if f_name.lower().endswith((".jpeg", ".jpg", ".png", ".docx", ".zip")) or f_name == "temp_input.md":
            try:
                os.path.join(root_dir, f_name)
            except:
                pass

# ==============================================================================
# HÀM XỬ LÝ TOÁN HỌC VÀ MARKDOWN THÔNG MINH CHO CẢ 2 TAB
# ==============================================================================

def clean_and_wrap_latex(latex_str):
    if not latex_str: return ""
    clean_str = latex_str.strip()
    if clean_str.startswith("$$") and clean_str.endswith("$$"):
        clean_str = clean_str[2:-2].strip()
    elif clean_str.startswith("$") and clean_str.endswith("$"):
        clean_str = clean_str[1:-1].strip()
    return f"${clean_str}$"

def clean_markdown_for_preview(md_text):
    if not md_text: return ""
    cleaned = re.sub(r'(\d+)%', r'\1\\%', md_text)
    cleaned = re.sub(r'\$\s*\$\s*', '', cleaned)
    cleaned = re.sub(r'(?<!\$)\\frac\{[^}]+\}\{[^}]+\}', r'$\g<0>$', cleaned)
    cleaned = re.sub(r'(?<!\$)\\(?:mathbb|alpha|beta|gamma|delta|pi|theta|sigma|omega|sum|int|in|neq|le|ge|cdot|pm)\b', r'$\g<0>$', cleaned)
    cleaned = re.sub(r'\\begin\{cases\}', r'$$\\begin{cases}', cleaned)
    cleaned = re.sub(r'\\end\{cases\}', r'\\end{cases}$$', cleaned)
    return cleaned

def markdown_to_json(md_text):
    if not md_text:
        return {"blocks": []}
    blocks = []
    lines = md_text.split("\n")
    current_block = []
    in_math = False
    math_buf = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 2:
            if current_block:
                blocks.append({"type": "text", "content": "\n".join(current_block)})
                current_block = []
            blocks.append({"type": "equation", "content": stripped})
            continue
        elif stripped.startswith("$$"):
            if in_math:
                math_buf.append(stripped)
                blocks.append({"type": "equation", "content": "\n".join(math_buf)})
                math_buf = []
                in_math = False
            else:
                if current_block:
                    blocks.append({"type": "text", "content": "\n".join(current_block)})
                    current_block = []
                in_math = True
                math_buf = [stripped]
            continue
            
        if in_math:
            math_buf.append(line)
            continue

        if stripped.startswith("#"):
            if current_block:
                blocks.append({"type": "text", "content": "\n".join(current_block)})
                current_block = []
            content = re.sub(r'^#+\s*', '', stripped)
            blocks.append({"type": "title", "content": content})
            continue

        img_match = re.search(r'!\[(.*?)\]\((.*?)\)', stripped)
        if img_match:
            if current_block:
                blocks.append({"type": "text", "content": "\n".join(current_block)})
                current_block = []
            blocks.append({"type": "image", "imageId": img_match.group(2)})
            continue

        if stripped == "":
            if current_block:
                blocks.append({"type": "text", "content": "\n".join(current_block)})
                current_block = []
        else:
            current_block.append(line)

    if current_block:
        blocks.append({"type": "text", "content": "\n".join(current_block)})

    return {"blocks": blocks}

def json_to_markdown(data):
    """Trình biên dịch thông minh chuyển đổi mọi cấu trúc JSON lồng nhau (Docling, MinerU, OCR) thành Markdown chuẩn."""
    if not isinstance(data, (dict, list)):
        return str(data)
    
    md_lines = []
    
    def parse_element(item):
        if isinstance(item, str):
            return item
        elif isinstance(item, dict):
            # Nếu là block chuẩn chứa văn bản hoặc công thức
            b_type = item.get("type", "text")
            content = item.get("content", item.get("text", ""))
            
            if b_type == "title" or item.get("label") == "section_header":
                return f"\n\n## {content}\n\n"
            elif b_type == "equation" or item.get("label") == "formula":
                eq = clean_and_wrap_latex(content)
                return f"\n$$\n{eq.strip('$')}\n$$\n\n"
            elif b_type == "image" or "image" in item:
                img_id = item.get("imageId", item.get("img_id", "img.jpg"))
                return f"\n\n![{img_id}]({img_id})\n\n"
            
            # Quét đệ quy nếu là cấu trúc lồng nhau (như Docling / MinerU spans & lines)
            sub_text = ""
            for k, v in item.items():
                if k in ["para_blocks", "blocks", "lines", "spans", "pages", "body", "texts"]:
                    if isinstance(v, list):
                        for sub_item in v:
                            sub_text += parse_element(sub_item) + " "
                    elif isinstance(v, dict):
                        sub_text += parse_element(v) + " "
                elif k in ["markdown", "content", "text"] and isinstance(v, str):
                    sub_text += v + "\n"
            return sub_text
        elif isinstance(item, list):
            return "".join([parse_element(sub) for sub in item])
        return ""

    # Quét toàn bộ dữ liệu JSON đầu vào
    parsed_result = parse_element(data)
    if not parsed_result.strip():
        # Fallback nếu không khớp cấu trúc trên
        parsed_result = json.dumps(data, ensure_ascii=False, indent=2)
        
    return parsed_result

def json_to_html_preview_body(json_data, images_dict):
    if not json_data or not isinstance(json_data, dict):
        return "<p>Không có dữ liệu JSON để hiển thị.</p>"
    
    blocks = json_data.get("blocks", [])
    if not blocks:
        # Nếu JSON là dạng thô, chuyển sang markdown rồi convert ngược lại blocks để preview
        md_fallback = json_to_markdown(json_data)
        json_data = markdown_to_json(md_fallback)
        blocks = json_data.get("blocks", [])
            
    html_out = []
    for b in blocks:
        if not isinstance(b, dict): continue
        b_type = b.get("type", "text")
        content = b.get("content", "")
        
        if b_type == "title":
            html_out.append(f"<h3 style='color:#2b6cb0; margin-top:15px;'>{content}</h3>")
        elif b_type == "equation":
            clean_eq = content.strip()
            if not clean_eq.startswith("$$"):
                clean_eq = f"$${clean_eq}$$"
            html_out.append(f"<div style='text-align:center; margin:10px 0;'>{clean_eq}</div>")
        elif b_type == "image":
            img_id = b.get("imageId", b.get("img_id", ""))
            matched_bytes = None
            for name, bytes_val in images_dict.items():
                if img_id in name or name in img_id:
                    matched_bytes = bytes_val
                    break
            if matched_bytes:
                b64 = base64.b64encode(matched_bytes).decode('utf-8')
                html_out.append(f"<p style='text-align:center;'><img src='data:image/jpeg;base64,{b64}' style='max-width:90%; height:auto; border-radius:4px;'/></p>")
            else:
                html_out.append(f"<p style='color:#718096;'><i>[Hình ảnh: {img_id}]</i></p>")
        else:
            if content:
                formatted_c = content.replace("\n", "<br>")
                html_out.append(f"<p>{formatted_c}</p>")
                
    return "".join(html_out)

def generate_pandoc_docx(data, images_dict):
    if isinstance(data, (dict, list)):
        md_text = json_to_markdown(data)
    else:
        md_text = str(data)

    md_text = clean_markdown_for_preview(md_text)

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_md_path = os.path.join(tmp_dir, "temp_input.md")
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
            
        for img_name, img_bytes in images_dict.items():
            with open(os.path.join(tmp_dir, os.path.basename(img_name)), "wb") as img_f:
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


# --- XỬ LÝ MÔ HÌNH MISTRAL ONLINE (TAB 1) ---
def process_with_mistral_with_rotation(file_bytes, file_name, file_type, raw_keys_str):
    if not MISTRAL_AVAILABLE:
        raise Exception("Chưa cài đặt mistralai SDK[cite: 1].")
    
    key_list = [k.strip() for k in re.split(r'[,\n]', raw_keys_str) if k.strip()]
    if not key_list:
        raise Exception("Không tìm thấy Mistral API Key hợp lệ.")

    last_error = None
    for idx, api_key in enumerate(key_list):
        try:
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
                    full_markdown += f"\n\n# Trang {p_idx+1}\n\n" + page_md
                    if hasattr(page, "images") and page.images:
                        for img in page.images:
                            if hasattr(img, "id") and hasattr(img, "image_base64") and img.image_base64:
                                img_id = img.id
                                img_b64 = img.image_base64
                                if "," in img_b64: img_b64 = img_b64.split(",")[1]
                                try:
                                    images_dict[img_id if img_id.lower().endswith((".jpeg", ".jpg", ".png")) else f"{img_id}.jpeg"] = base64.b64decode(img_b64)
                                except: pass
            
            md_clean = clean_markdown_for_preview(full_markdown)
            json_preview = markdown_to_json(md_clean)
            return json_preview, md_clean, images_dict
        except Exception as e:
            last_error = e
            continue
    raise Exception(f"Tất cả các Mistral Key đều thất bại. Lỗi: {str(last_error)}")


# --- HÀM RENDER PREVIEW BOX ---
def render_ai_preview_box(ai_label, json_data, markdown_text, images_dict, file_name):
    st.subheader(f"📊 Kết quả từ: `{ai_label}`")
    
    if not json_data and markdown_text:
        json_data = markdown_to_json(markdown_text)
    elif json_data and not markdown_text:
        markdown_text = json_to_markdown(json_data)

    docx_bytes = generate_pandoc_docx(markdown_text, images_dict) if markdown_text else None

    col1, col2, col3 = st.columns(3)
    with col1:
        if docx_bytes:
            st.download_button(f"📥 Tải Word (Pandoc) [{ai_label}]", docx_bytes, f"{file_name}_{ai_label}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", type="primary", use_container_width=True, key=f"dl_{ai_label}")
    with col2:
        if markdown_text:
            st.download_button(f"📥 Tải Markdown (.md) [{ai_label}]", markdown_text, f"{file_name}_{ai_label}.md", "text/markdown", use_container_width=True, key=f"dl_md_{ai_label}")
    with col3:
        if json_data:
            st.download_button(f"📥 Tải JSON [{ai_label}]", json.dumps(json_data, ensure_ascii=False, indent=2), f"{file_name}_{ai_label}.json", "application/json", use_container_width=True, key=f"dl_json_{ai_label}")

    preview_body_html = json_to_html_preview_body(json_data, images_dict)
    
    preview_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
        <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/contrib/auto-render.min.js"></script>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 10px; background: #fff; color: #2d3748; }}
            .btn-action {{ padding: 8px 16px; color: white; background: #2b6cb0; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; margin-bottom: 10px; }}
            .preview-card {{ background: #fff; padding: 20px; border-radius: 8px; border: 1px solid #cbd5e0; max-height: 450px; overflow-y: auto; line-height: 1.6; }}
        </style>
    </head>
    <body>
        <button class="btn-action" onclick="copyContent()">📋 Sao chép nhanh [{ai_label}] (Dán Word)</button>
        <div class="preview-card" id="box_{ai_label}">
            {preview_body_html}
        </div>
        <script>
        document.addEventListener("DOMContentLoaded", function() {{
            renderMathInElement(document.getElementById('box_{ai_label}'), {{
                delimiters: [
                    {{left: '$$', right: '$$', display: true}},
                    {{left: '$', right: '$', display: false}},
                    {{left: '\\\\(', right: '\\\\)', display: false}},
                    {{left: '\\\\[', right: '\\\\]', display: true}}
                ],
                throwOnError: false
            }});
        }});
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


# ==========================================
# GIAO DIỆN CHÍNH (2 TABS)
# ==========================================
st.title("⚡ p2w.py - Multi-AI Concurrent & Rotation Suite")
st.write("Hệ thống xử lý: **Preview qua JSON + KaTeX** & **Xuất Word qua Pandoc + Markdown**.")

tab1, tab2 = st.tabs([
    "🚀 Tab 1: Mistral Online", 
    "📁 Tab 2: Xử lý & Chuẩn hoá Offline (Chống Tràn RAM)"
])

# ==========================================
# TAB 1: MISTRAL ONLINE
# ==========================================
with tab1:
    st.subheader("🔑 Cấu hình Mistral API Key")
    m_keys = st.text_input("Danh sách Mistral API Keys:", value=st.session_state.saved_mistral_keys_raw, type="password")
    if st.button("Lưu Keys"):
        st.session_state.saved_mistral_keys_raw = m_keys
        with open("api_key_Mistral.txt", "w", encoding="utf-8") as f: f.write(m_keys)
        st.success("Đã lưu thành công!")
        st.rerun()

    pipeline_file = st.file_uploader("📥 Tải file tài liệu (PDF, Ảnh) để xử lý Online", type=["pdf", "png", "jpg", "jpeg"], key="tab1_upload")

    if pipeline_file and st.button("🚀 Chạy Mistral OCR Online", type="primary"):
        with st.spinner("⏳ Đang xử lý file qua Mistral OCR..."):
            try:
                json_res, md_res, img_res = process_with_mistral_with_rotation(
                    pipeline_file.getvalue(), pipeline_file.name, pipeline_file.type, st.session_state.saved_mistral_keys_raw
                )
                st.session_state.ai_results["Mistral"] = {
                    "json": json_res, "md": md_res, "imgs": img_res, "name": pipeline_file.name.rsplit(".", 1)[0]
                }
                st.success("🎉 Thành công!")
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi: {e}")

    res_m = st.session_state.ai_results.get("Mistral", {})
    if res_m.get("json") or res_m.get("md"):
        render_ai_preview_box("Mistral", res_m.get("json"), res_m.get("md"), res_m.get("imgs", {}), res_m.get("name", "Document"))


# ==========================================
# TAB 2: XỬ LÝ OFFLINE (TỐI ƯU ĐỌC ZIP / JSON / MD CHUẨN)
# ==========================================
with tab2:
    st.subheader("📦 Xử lý Offline: Nạp ZIP, JSON, Markdown và Ảnh để Dựng Word")
    offline_file = st.file_uploader("📥 Tải lên gói tệp (ZIP, JSON hoặc Markdown)", type=["zip", "json", "md", "markdown"], key="tab2_pkg")

    if st.button("⚙️ Xử lý & Dựng Word tài liệu Offline", type="primary", key="btn_run_offline"):
        if offline_file is None:
            st.warning("Vui lòng tải lên gói tệp trước!")
        else:
            file_ext = offline_file.name.rsplit(".", 1)[1].lower()
            file_base = offline_file.name.rsplit(".", 1)[0]

            with st.spinner("⏳ Đang phân tích, trích xuất cấu trúc và tổng hợp dữ liệu offline..."):
                try:
                    found_json = {}
                    md_content = ""
                    images_dict = {}

                    if file_ext == "zip":
                        with tempfile.TemporaryDirectory() as tmp_dir:
                            with zipfile.ZipFile(io.BytesIO(offline_file.getvalue())) as z:
                                z.extractall(tmp_dir)
                            for root, dirs, files in os.walk(tmp_dir):
                                for file in files:
                                    full_p = os.path.join(root, file)
                                    if "__MACOSX" in full_p: continue
                                    if file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) or "images/" in full_p.replace("\\", "/"):
                                        with open(full_p, "rb") as img_f:
                                            images_dict[file] = img_f.read()
                                    elif file.lower() == "output.md" or file.endswith(".md"):
                                        with open(full_p, "r", encoding="utf-8", errors="ignore") as md_f:
                                            md_content = md_f.read()
                                    elif file.endswith(".json"):
                                        try:
                                            with open(full_p, "r", encoding="utf-8") as j_f:
                                                found_json = json.load(j_f)
                                        except: pass
                        if not md_content and found_json:
                            md_content = json_to_markdown(found_json)
                    elif file_ext == "json":
                        found_json = json.loads(offline_file.getvalue().decode("utf-8"))
                        md_content = json_to_markdown(found_json)
                    elif file_ext in ["md", "markdown"]:
                        md_content = offline_file.getvalue().decode("utf-8", errors="ignore")
                        found_json = markdown_to_json(md_content)

                    clean_md = clean_markdown_for_preview(md_content)
                    if not found_json or "blocks" not in found_json:
                        found_json = markdown_to_json(clean_md)

                    st.session_state.ai_results["Offline Processor"] = {
                        "json": found_json,
                        "md": clean_md,
                        "imgs": images_dict,
                        "name": file_base
                    }
                    st.success("🎉 Xử lý gói offline thành công!")
                    st.rerun()
                except Exception as e:
                    log_error(f"Lỗi xử lý file Offline ở Tab 2: {e}")
                    st.error(f"Lỗi khi xử lý: {e}")

    res_off = st.session_state.ai_results.get("Offline Processor", {})
    if res_off.get("json") or res_off.get("md"):
        render_ai_preview_box("Offline Processor", res_off.get("json"), res_off.get("md"), res_off.get("imgs", {}), res_off.get("name", "Document"))

# --- XEM NHẬT KÝ HỆ THỐNG ---
st.divider()
with st.expander("🛠️ Xem Nhật ký hệ thống (System Logs)"):
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as log_file:
            st.text_area("Nội dung file app.log", log_file.read(), height=250)
        if st.button("Xóa lịch sử log"):
            open(LOG_FILE, "w", encoding="utf-8").close()
            st.success("Đã làm sạch file log!")
            st.rerun()