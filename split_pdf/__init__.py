from fastapi import APIRouter, UploadFile, File, Form, Response, HTTPException
from io import BytesIO
import zipfile
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
from pyzbar.pyzbar import decode as decode_barcode
import PyPDF2
import json
import time
import logging

Image.MAX_IMAGE_PIXELS = None

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_text_from_image(image: Image.Image):
    try:
        return pytesseract.image_to_string(image)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR-fout: {str(e)}")

def get_barcodes_from_image(image: Image.Image):
    gray = image.convert("L")
    scale = 2
    resized = gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)
    bw = resized.point(lambda x: 0 if x < 128 else 255, '1')
    barcodes = decode_barcode(bw)
    return [b.data.decode('utf-8') for b in barcodes]

@router.post("/split")
async def split_pdf(
    file: UploadFile = File(...),
    split_size: int = Form(None),
    keyword: str = Form(None),
    barcode: bool = Form(False)
):
    methods_chosen = sum([
        bool(split_size is not None),
        bool(keyword),
        barcode
    ])
    if methods_chosen != 1:
        raise HTTPException(status_code=400, detail="Kies exact één splitsoptie: split_size, keyword of barcode.")

    start_time = time.perf_counter()

    try:
        contents = await file.read()
        bestandsgrootte_mb = len(contents) / 1024 / 1024
        logger.info(f"Bestand ontvangen: {file.filename} ({bestandsgrootte_mb:.2f} MB)")

        methode = "split_size" if split_size is not None else "keyword" if keyword else "barcode"
        logger.info(f"Splitsmethode: {methode}")

        pdf_reader = PyPDF2.PdfReader(BytesIO(contents))
        total_pages = len(pdf_reader.pages)
        logger.info(f"Totaal aantal pagina’s: {total_pages}")

        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            if keyword or barcode:
                dpi = 300 if barcode else 150
                images = convert_from_bytes(contents, dpi=dpi)
                split_points = []

                if keyword:
                    ocr_results = {}

                for i in range(total_pages):
                    image = images[i]

                    if keyword:
                        text = extract_text_from_image(image)
                        ocr_results[f"page_{i+1}"] = text
                        if keyword.lower() in text.lower():
                            split_points.append(i)

                    elif barcode:
                        barcodes = get_barcodes_from_image(image)
                        if barcodes:
                            split_points.append(i)

                if not split_points:
                    zip_file.writestr("full_pdf.pdf", contents)
                else:
                    split_start = 0
                    for split_page in split_points:
                        if split_page > split_start:
                            writer = PyPDF2.PdfWriter()
                            for i in range(split_start, split_page):
                                writer.add_page(pdf_reader.pages[i])
                            range_name = f"pages_{split_start + 1}_{split_page}.pdf"
                            with BytesIO() as buffer:
                                writer.write(buffer)
                                buffer.seek(0)
                                zip_file.writestr(range_name, buffer.read())
                        split_start = split_page

                    if split_start < total_pages:
                        writer = PyPDF2.PdfWriter()
                        for i in range(split_start, total_pages):
                            writer.add_page(pdf_reader.pages[i])
                        range_name = f"pages_{split_start + 1}_{total_pages}.pdf"
                        with BytesIO() as buffer:
                            writer.write(buffer)
                            buffer.seek(0)
                            zip_file.writestr(range_name, buffer.read())

                if keyword:
                    zip_file.writestr("ocr_results.json", json.dumps(ocr_results, indent=2))

            else:
                for start_page in range(0, total_pages, split_size):
                    end_page = min(start_page + split_size, total_pages)
                    writer = PyPDF2.PdfWriter()
                    for i in range(start_page, end_page):
                        writer.add_page(pdf_reader.pages[i])
                    range_name = f"pages_{start_page + 1}_{end_page}.pdf"
                    with BytesIO() as buffer:
                        writer.write(buffer)
                        buffer.seek(0)
                        zip_file.writestr(range_name, buffer.read())

        zip_buffer.seek(0)

        duration = time.perf_counter() - start_time
        logger.info(f"Split-verwerkingstijd: {duration:.2f} seconden")

        return Response(
            content=zip_buffer.read(),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=split_pages.zip"}
        )

    except Exception as e:
        logger.error(f"Fout tijdens split-verwerking: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Fout: {str(e)}")
