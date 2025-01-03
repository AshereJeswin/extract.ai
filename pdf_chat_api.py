from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from pydantic import BaseModel
from typing import List
import os
from dotenv import load_dotenv
import google.generativeai as genai
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains.question_answering import load_qa_chain
from langchain.prompts import PromptTemplate
from PyPDF2 import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from fastapi.staticfiles import StaticFiles

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in environment variables")

app = FastAPI(
    title = " CHATBOT SYSTEM",
    description=(
        " A system that allows users to upload PDF documents and interact with them. "
        "The system is capable of ingesting and interpreting uploaded documents to provide accurate, fact-based responses quickly and reliably"
    ),
    version="1.0.0"
    
)
try:
    genai.configure(api_key=GOOGLE_API_KEY)
except Exception as e:
    raise Exception(f"Error configuring Google API: {str(e)}")

embed_model = HuggingFaceEmbeddings(
    model_name="BAAI/bge-small-en",
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)

class UserQuestion(BaseModel):
    question: str


def get_pdf_text(pdf_docs: List[UploadFile]):
    text = ""
    for pdf in pdf_docs:
        pdf_reader = PdfReader(pdf.file)
        for page in pdf_reader.pages:
            text += page.extract_text()
    return text


def get_text_chunks(text: str):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=10000, chunk_overlap=1000)
    return text_splitter.split_text(text)


def get_vector_store(text_chunks: List[str]):
    vector_store = Chroma.from_texts(
        texts=text_chunks,
        embedding=embed_model,
        persist_directory="chroma_db"
    )
    vector_store.persist()
    return vector_store


def get_conversational_chain():
    prompt_template = """
    Answer the question as detailed as possible from the provided context, make sure to provide all the details, if the answer is not in
    provided context just say, "answer is not available in the context", don't provide the wrong answer\n\n
    Context:\n {context}?\n
    Question: \n{question}\n
    Answer:
    """
    model = ChatGoogleGenerativeAI(
        model="gemini-pro",
        temperature=0.3,
        google_api_key=GOOGLE_API_KEY
    )
    prompt = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
    return load_qa_chain(model, chain_type="stuff", prompt=prompt)

# Root route
@app.get("/")
async def read_root():
    """
    Welcome route for the PDF Chat API.
    """
    return {"message": "Welcome to the Ask Docs API!"}


# Upload PDF and ask questions
@app.post("/ask_question/")
async def ask_question(
    user_question: str = Form(...),
    pdf_files: List[UploadFile] = File(...)
):
    """
    Upload a PDF document and ask a question about its content.
    - *user_question*: The question to ask based on the PDF content.
    - *pdf_files*: One or more PDF files to process.
    """
    try:
        raw_text = get_pdf_text(pdf_files)
        
        text_chunks = get_text_chunks(raw_text)
        
        get_vector_store(text_chunks)

        vector_store = Chroma(
            persist_directory="chroma_db",
            embedding_function=embed_model
        )

        docs = vector_store.similarity_search(user_question)
        
        chain = get_conversational_chain()

        response = chain(
            {"input_documents": docs, "question": user_question},
            return_only_outputs=True
        )

        return {"answer": response["output_text"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing question: {str(e)}")