import streamlit as st
from PIL import Image
import pytesseract
from dotenv import load_dotenv
import os
from openai import OpenAI
from invoice_utils import *
from imap_tools import MailBox
from azure.storage.blob import BlobServiceClient, ContentSettings
import io
import pandas as pd
import json
from datetime import datetime
import requests
import fitz  # PyMuPDF


# -------------------- Setup --------------------
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EMAIL = 'kkarthi00197@gmail.com'
APP_PASSWORD = os.getenv("APP_PASSWORD")
SAVE_FOLDER = './downloaded_invoices'
today_str = datetime.today().strftime('%d-%b-%Y')  # e.g., '23-Jul-2025'
SEARCH_CRITERIA = f'UNSEEN SENTSINCE {today_str}'

account_name = "saadftraining"
access_key = os.getenv("ACCESS_KEY")
container_name = "invoices"
adls_directory = "downloaded_invoices"

# Session state init
for key in ["uploaded_image", "extracted_text", "extracted_data_json", "db_success", "uploaded_file", "save_path"]:
    if key not in st.session_state:
        st.session_state[key] = None

# Initialize session state
if "uploaded_files" not in st.session_state:
    st.session_state["uploaded_files"] = []
if "saved_files" not in st.session_state:
    st.session_state["saved_files"] = []

# -------------------- UI Layout --------------------
st.set_page_config(page_title="Invoice Extractor", layout="wide")
st.title("📄 Invoice Automation Dashboard")

st.markdown("---")



# -------------------- Step 1: Check Mail --------------------
def is_invoice_related(filename):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that determines whether a filename is related to an invoice."},
            {"role": "user", "content": f"Is the file '{filename}' related to an invoice? Reply 'Yes' or 'No'."}
        ],
        temperature=0
    )
    answer = response.choices[0].message.content.strip().lower()
    return 'yes' in answer


# # Display total Invoices already processed in main page
# st.sidebar.title("📊 Processed Invoices")
# if "processed_invoices" not in st.session_state:
#     st.session_state["processed_invoices"] = 0
# st.sidebar.markdown(f"**Total Processed Invoices:** {st.session_state['processed_invoices']}")



# Initialize KPI values only once
if "total_invoices" not in st.session_state:
    st.session_state["total_invoices"] = get_invoice_count()
    st.session_state["total_vendors"] = get_vendor_count()
    st.session_state["total_purchase_orders"] = get_po_count()

# Function to update KPI values after processing
def update_kpis():
    st.session_state["total_invoices"] = get_invoice_count()
    st.session_state["total_vendors"] = get_vendor_count()
    st.session_state["total_purchase_orders"] = get_po_count()

# Function to display KPI cards
def display_kpis():
    st.markdown("### 📊 Summary Metrics")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("🧾 Total Invoices Processed", st.session_state.get("total_invoices", 0))

    with col2:
        st.metric("🏢 Total Vendors", st.session_state.get("total_vendors", 0))

    with col3:
        st.metric("📦 Total Purchase Orders", st.session_state.get("total_purchase_orders", 0))

# Show KPI section
display_kpis()

def extract_text_from_pdf(pdf_bytes):
    text = ""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        text += page.get_text()
    return text

with st.container():
    
    process_from_email = st.button("📩 Process Invoice from Email")
    uploaded_file = st.file_uploader("📁 Or upload invoice PDF", type=["pdf"])

    st.session_state["saved_files"] = []
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    today = datetime.now()
    count = 0
    # Unified logic for email & upload
    if process_from_email:
        with st.spinner("Connecting to mailbox and checking for attachments..."):
            with MailBox('imap.gmail.com').login(EMAIL, APP_PASSWORD, initial_folder='INBOX') as mailbox:
                for msg in mailbox.fetch(criteria=SEARCH_CRITERIA, reverse=True):
                    for att in msg.attachments:
                        filename = att.filename
                        if filename.lower().endswith('.pdf') and is_invoice_related(filename):
                            save_path = os.path.join(SAVE_FOLDER, filename)
                            with open(save_path, 'wb') as f:
                                f.write(att.payload)
                            st.session_state["saved_files"].append(save_path)
                            st.success(f"✅ Saved invoice: **{filename}**")
                            count += 1

                    mailbox.flag(msg.uid, ['\\Seen'], True)

    elif uploaded_file is not None:
        filename = uploaded_file.name
        if filename.lower().endswith('.pdf') and is_invoice_related(filename):
            save_path = os.path.join(SAVE_FOLDER, filename)
            with open(save_path, 'wb') as f:
                f.write(uploaded_file.getvalue())
            st.session_state["saved_files"].append(save_path)
            st.success(f"✅ Saved invoice: **{filename}**")
            count += 1

    if count == 0:
        st.warning("⚠️ No invoice attachments found today.")

                        

if st.session_state["saved_files"]:
    with st.expander(filename, expanded=True):
        connection_string = f"DefaultEndpointsProtocol=https;AccountName={account_name};AccountKey={access_key};EndpointSuffix=core.windows.net"
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)

        # for save_path in st.session_state["saved_files"]:
        blob_path = f"{adls_directory}/{os.path.basename(save_path)}"
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)

        with open(save_path, "rb") as data:
            file_data = data.read()
            blob_client.upload_blob(file_data, overwrite=True, content_settings=ContentSettings(content_type='application/pdf'))
            st.session_state["uploaded_file"] = io.BytesIO(file_data)

        st.success(f"✅ Uploaded: `{blob_path}`")


        if st.session_state["uploaded_file"]:
            with st.spinner("Extracting text from PDF..."):
                extracted_text = extract_text_from_pdf(st.session_state["uploaded_file"].getvalue())
                st.session_state.extracted_text = extracted_text
            st.success("✅ Text extracted from PDF.")


    
        if st.session_state.extracted_text:
            # Show extracted text in streamlit
            # with st.expander("📜 Extracted Text", expanded=True):
            st.text_area("Extracted Text", st.session_state.extracted_text, height=300)

            with st.spinner("Extracting structured fields using GPT..."):
                prompt = f"""
                You are an expert in extracting structured data from OCR'd invoices.

                From the following OCR text, extract and return the details below in valid JSON format:

                1. Bill To Name  
                2. Bill To Address  
                3. Ship To Name  
                4. Ship To Address  
                5. Date of Exportation  
                6. Air Way bill Number  
                7. Invoice Line Items: A list of items, where each item includes:
                - Description
                - Quantity
                - Unit Price
                - Total

                Make sure Quantity, Unit Price and Total are numbers.
                Date of Exportation should be in %d/%m/%Y format.

                OCR Text:
                \"\"\"{st.session_state.extracted_text}\"\"\"
                """

                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that extracts structured invoice data."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0
                )
                st.session_state.extracted_data_json = extract_json_block(response.choices[0].message.content)
            st.success("✅ Structured invoice data extracted.")

        if st.session_state.extracted_data_json:
            with st.container():
                # st.subheader("📦 Extracted Invoice Data")
                # st.code(st.session_state.extracted_data_json, language="json")
                # Load JSON
                invoice_data = st.session_state.extracted_data_json
                print(invoice_data)

                # Display Header Information (non-line-item fields)
                header_fields = {
                    "Air Way bill Number": invoice_data.get("Air Way bill Number"),
                    "Date of Exportation": invoice_data.get("Date of Exportation"),
                    "Bill To Name": invoice_data.get("Bill To Name"),
                    "Bill To Address": invoice_data.get("Bill To Address"),
                    "Ship To Name": invoice_data.get("Ship To Name"),
                    "Ship To Address": invoice_data.get("Ship To Address"),
                }
                st.markdown("### 🧾 Invoice Summary")
                st.table(pd.DataFrame.from_dict(header_fields, orient='index', columns=['Value']))

                # Display Line Items
                line_items = invoice_data.get("Invoice Line Items", [])
                if line_items:
                    st.markdown("### 📄 Line Items")
                    st.dataframe(pd.DataFrame(line_items))  # or st.table() if preferred
                else:
                    st.warning("No line items found.")


    
        if st.session_state.extracted_data_json:
            with st.spinner("Inserting into database..."):
                # try:
                body, success = insert_invoice_to_sql(st.session_state.extracted_data_json)
                st.session_state.db_success = success
                update_kpis()
                # except Exception as e:
                #     st.error(f"❌ Failed: {e}")
        else:
            st.warning("⚠️ No extracted data found. Run OCR + GPT first.")

        # # Get EMAIL from vendors table
        # receiver_email = get_vendor_email(invoice_data.get("Bill To Name", ""))
        # if receiver_email:
        
        # Generate body for Logic App to include 
        LOGIC_APP_URL = 'https://prod-24.centralindia.logic.azure.com:443/workflows/67c34b93251049438209e60b92ed8900/triggers/When_a_HTTP_request_is_received/paths/invoke?api-version=2016-10-01&sp=%2Ftriggers%2FWhen_a_HTTP_request_is_received%2Frun&sv=1.0&sig=mPL7bK0SzpHHs9Z08twKg5yssjboc36QVR-Dnx0lS4c'
        payload = {
        "subject": f"Status for Invoice with Air Way Bill Number {invoice_data.get('Air Way bill Number', 'N/A')}",
        "body": body,
        "receiver": 'venkat@logesys.com'
        }
        
        response = requests.post(LOGIC_APP_URL, json=payload)
        st.success("✅ Mail Sent")
    

            

# 🚀 After processing invoices
st.session_state["total_invoices"] = get_invoice_count()
st.session_state["total_vendors"] = get_vendor_count()
st.session_state["total_purchase_orders"] = get_po_count()


with st.sidebar:
    st.title("🧾 Invoice Summary")

    saved_files = st.session_state.get("saved_files", [])

    if saved_files:
        st.markdown(f"**🗂 Total Files Processed:** {len(saved_files)}")

        with st.expander("📄 Processed Files", expanded=False):
            for file_path in saved_files:
                file_name = os.path.basename(file_path)
                try:
                    file_size_kb = os.path.getsize(file_path) // 1024
                    st.markdown(f"- `{file_name}` ({file_size_kb} KB)")
                except FileNotFoundError:
                    st.warning(f"- `{file_name}` (File not found)")
    else:
        st.info("📪 No invoice loaded yet")


    # st.markdown("---")
    # st.markdown("### 📊 Processing Status")

    # def stage_icon(stage_flag):
    #     return "✅" if stage_flag else "❌"

    # st.markdown(f"{stage_icon(bool(st.session_state['save_path']))} Fetched from Email")
    # st.markdown(f"{stage_icon(bool(st.session_state['uploaded_file']))} Uploaded to Blob")
    # st.markdown(f"{stage_icon(bool(st.session_state['extracted_text']))} OCR Extracted")
    # st.markdown(f"{stage_icon(bool(st.session_state['extracted_data_json']))} Structured by GPT")
    # st.markdown(f"{stage_icon(bool(st.session_state['db_success']))} Inserted to DB")

        
    # if st.session_state["save_path"]:
    #     st.markdown("---")
    #     st.markdown("### 🕒 Timestamps")
    #     st.markdown(f"**Started:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


    st.markdown("---")
    st.markdown("### ℹ️ About This App")
    st.markdown("This app automates invoice processing using:")
    st.markdown("- Gmail API")
    st.markdown("- Azure Blob Storage")
    st.markdown("- OCR with Tesseract")
    st.markdown("- OpenAI for structured extraction")
    st.markdown("- SQL DB for storage")



        # # UI: Step 3 - Preview Uploaded Files
        # if st.session_state["uploaded_files"]:
        #     st.subheader("🖼️ Step 3: Preview Uploaded Invoices")
        #     file_names = [f["name"] for f in st.session_state["uploaded_files"]]
        #     selected_file = st.selectbox("Select an invoice to preview:", file_names)

        #     for f in st.session_state["uploaded_files"]:
        #         if f["name"] == selected_file:
        #             with st.expander("🖼️ Preview Uploaded Invoice", expanded=True):
        #                 st.image(Image.open(f["data"]), caption=selected_file, use_container_width=False)
        #             break


# if st.session_state.db_success:
#     st.success("✅ Process Completed Successfully.")
