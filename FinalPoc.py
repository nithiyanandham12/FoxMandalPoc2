import streamlit as st  
from PyPDF2 import PdfReader, PdfWriter
import tempfile
import os
import requests
from googletrans import Translator
from dotenv import load_dotenv
import pypandoc
import json

load_dotenv()

API_KEY = os.getenv("API_KEY")
PROJECT_ID = os.getenv("PROJECT_ID")
ASSISTO_API = os.getenv("ASSISTO_API")

Prompt1 = '''You are a Senior Legal Associate at a top-tier Indian law firm (e.g., Fox Mandal & Associates), specializing in property due diligence and land title verification.

Your task is to draft a professionally formatted, legally precise, and highly detailed “Report on Title” based strictly on the input provided. The input contains OCR-extracted and translated data from government land records, including RTCs, Mutation Registers, Deeds, and Encumbrance Certificates.

⚖️ LEGAL GUIDELINES
✅ Use only the data found in the input.

❌ Do not hallucinate, infer, or assume facts.

⛔ If information is incomplete or not found, insert “Not Available”.

🧾 Maintain a formal legal tone consistent with elite law firm standards.

📐 STRUCTURE & FORMATTING INSTRUCTIONS
Format the report in Markdown.

Begin with a header:
Report On Title
Confidential | Not for Circulation
Prepared exclusively for [Client Name]

Use numbered Roman section headers (I, II, III...)

Use bordered tables (Markdown |) where applicable.

Maintain the following sections and structure:

🧱 REQUIRED SECTIONS
I. DESCRIPTION OF THE LANDS
Table format:
| Survey No. | Extent | A-Kharab | Village | Taluk | District |

II. LIST OF DOCUMENTS REVIEWED
Table format:
| Sl. No. | Document Description | Date / Document No. | Issuing Authority |

III. DEVOLUTION OF TITLE

Timeline table:
| Period | Title Holder(s) | Nature of Right / Document Basis |

Bullet summary (4–6 points) of title flow, mutations, gifts, partitions, etc.

IV. ENCUMBRANCE CERTIFICATE

Use period-wise tables:
| Period | Document Description | Encumbrance Type | Remarks |

List mortgages noted in mutation registers separately.

V. OTHER OBSERVATIONS
Markdown table for boundary details:


Direction	Boundary Details
East	
West	
North	
South	
Also include bullet notes on:

Land ceiling compliance

Grant land / Inam / SC-ST restrictions

Alienation restrictions

Endorsements (PTCL / Tenancy / Acquisition)

VI. FAMILY TREE / GENEALOGICAL DETAILS

List of members, relationships, ages, marital status

Specify if notarized / government issued

VII. INDEPENDENT VERIFICATIONS
Bullet points covering:

Sub-Registrar searches

Revenue department checks

11E Sketch or physical inspection

VIII. LITIGATION SEARCH RESULTS
Bullet format:

Searches conducted by [Advocate Name]

Note any pending litigation or state "No litigation found"

IX. SPECIAL CATEGORY LANDS
Table format:


Category	Status
SC/ST	Yes/No
Minor	Yes/No
Inam	Yes/No
Grant Land	Yes/No
X. OPINION AND RECOMMENDATION

Provide formal legal opinion (paragraph format)

Mention current title holder(s), marketability, pending clarifications

Include table:
| Name of Owner / Co-signatory | Type of Right / Share |

XI. CONTACT DETAILS

Prepared by [Full Name]

Designation

Firm name

Contact info (phone + email)
'''

# Function to extract text via OCR (page-by-page)
def ocr_each_page(uploaded_pdf):
    translator = Translator()
    translated_pages = {}

    with tempfile.TemporaryDirectory() as tempdir:
        reader = PdfReader(uploaded_pdf)
        total_pages = len(reader.pages)
        status = st.empty()

        for i, page in enumerate(reader.pages):
            status.markdown(f"🔍 **Processing Page {i+1}/{total_pages}...**")

            page_path = os.path.join(tempdir, f"page_{i+1}.pdf")
            writer = PdfWriter()
            writer.add_page(page)

            with open(page_path, "wb") as f:
                writer.write(f)

            ocr_response = requests.post(
                ASSISTO_API,
                files={"file": open(page_path, "rb")}
            )

            if ocr_response.status_code == 200:
                result = ocr_response.json()
                result.pop("request_id", None)

                # Translate the entire JSON as a string
                raw_json_str = json.dumps(result, ensure_ascii=False, indent=2)
                # print(raw_json_str)

                try:
                    translated = translator.translate(raw_json_str, src='kn', dest='en').text
                    translated_pages[f"Page {i+1}"] = translated
                except Exception as e:
                    translated_pages[f"Page {i+1}"] = f"[Translation failed: {str(e)}]"
            else:
                translated_pages[f"Page {i+1}"] = f"[OCR failed: {ocr_response.status_code}]"

    print(translated_pages)
    return translated_pages
    


def chunk_pages(translated_dict, chunk_size=15):
    pages = list(translated_dict.items())
    return [dict(pages[i:i + chunk_size]) for i in range(0, len(pages), chunk_size)]


def get_ibm_access_token(api_key):
    url = "https://iam.cloud.ibm.com/identity/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": api_key
    }
    response = requests.post(url, headers=headers, data=data)
    return response.json()["access_token"]


def send_chunk_to_watsonx(chunk_text, access_token):
    url = "https://us-south.ml.cloud.ibm.com/ml/v1/text/generation?version=2024-01-15"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}"
    }

    payload = {
        "input": Prompt1 + chunk_text,
        "parameters": {
            "decoding_method": "greedy",
            "max_new_tokens": 8100,
            "min_new_tokens": 0,
            "stop_sequences": [],
            "repetition_penalty": 1
        },
        "model_id": "meta-llama/llama-3-3-70b-instruct",
        "project_id": PROJECT_ID
    }

    response = requests.post(url, headers=headers, json=payload)

    try:
        result = response.json()
        return result["results"][0]["generated_text"]
    except Exception as e:
        return f"[Watsonx response error: {str(e)} - Raw: {response.text}]"


def save_to_word_from_markdown(markdown_text, upload_file_name):
    pypandoc.download_pandoc()
    base_name = os.path.splitext(upload_file_name)[0]
    file_name = f"{base_name} AI Summary.docx"
    output_path = os.path.join(os.getcwd(), file_name)
    pypandoc.convert_text(markdown_text, 'docx', format='md', outputfile=output_path)
    return output_path


# 🔥 Streamlit UI Starts
st.set_page_config(page_title="FOX MANDEL OCR-AI", layout="wide")
st.title("📄 FOX MANDEL - POC")

uploaded_file = st.file_uploader("📄 Upload Multi-Page PDF (Kannada-English)", type=["pdf"])

if uploaded_file:
    with st.spinner("🔍 Running OCR & Translation..."):
        translated_pages = ocr_each_page(uploaded_file)

    try:
        with st.spinner("🔐 Getting IBM Watsonx Token..."):
            token = get_ibm_access_token(API_KEY)

        chunks = chunk_pages(translated_pages, chunk_size=90)
        watsonx_outputs = []

        for i, chunk in enumerate(chunks):
            chunk_text = "\n".join(chunk.values())
            with st.spinner(f"🤖 Sending Chunk {i + 1} of {len(chunks)} to Watsonx..."):
                result = send_chunk_to_watsonx(chunk_text, token)
                watsonx_outputs.append(result)

        final_output = "\n\n".join(watsonx_outputs)
        st.subheader("📝 Final Watsonx Output")
        st.write(final_output)

        # Generate Word doc
        if "word_generated" not in st.session_state:
            with st.spinner("🧾 Generating Word document from Markdown..."):
                word_path = save_to_word_from_markdown(final_output, uploaded_file.name)
                st.session_state.word_generated = True
                st.session_state.word_path = word_path

        if "word_path" in st.session_state:
            with open(st.session_state.word_path, "rb") as f:
                st.download_button("📥 Download Word Document", f, file_name=os.path.basename(st.session_state.word_path))

    except Exception as e:
        st.error(f"❌ Error: {e}")