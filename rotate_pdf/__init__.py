from fastapi import APIRouter, UploadFile, File, Response, HTTPException
from pdf2image import convert_from_bytes
from PIL import Image
import pytesseract
import logging
import io
import time
import threading

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ocr_lock = threading.Lock()

def detect_rotation_angle(image: Image.Image) -> int:
    try:
        osd = pytesseract.image_to_osd(image)
        for line in osd.splitlines():
            if "Rotate" in line:
                return int(line.split(":")[1].strip())
    except Exception as e:
        logger.error(f"Fout bij rotatiedetectie: {e}")
    return 0

def correct_image_rotation(pil_image: Image.Image, angle: int) -> Image.Image:
    if angle == 90:
        return pil_image.rotate(-90, expand=True)
    elif angle == 180:
        return pil_image.rotate(-180, expand=True)
    elif angle == 270:
        return pil_image.rotate(-270, expand=True)
    return pil_image

@router.post("/rotate")
async def rotate_pdf(file: UploadFile = File(...)):
    if not ocr_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="OCR-verwerking is al bezig. Probeer het zo meteen opnieuw.")

    start_time = time.perf_counter()

    try:
        contents = await file.read()
        bestandsgrootte_mb = len(contents) / 1024 / 1024
        logger.info(f"Bestand ontvangen: {file.filename} ({bestandsgrootte_mb:.2f} MB)")

        images = convert_from_bytes(contents, dpi=100)

        rotated_images = []
        for img in images:
            angle = detect_rotation_angle(img)
            logger.info(f"Gevonden rotatiehoek: {angle} graden")
            rotated = correct_image_rotation(img, angle)
            rotated_images.append(rotated.convert("RGB"))

        output_buffer = io.BytesIO()
        rotated_images[0].save(output_buffer, format="PDF", save_all=True, append_images=rotated_images[1:])
        pdf_bytes = output_buffer.getvalue()

        resultaat_mb = len(pdf_bytes) / 1024 / 1024
        logger.info(f"Rotatie voltooid, PDF is {resultaat_mb:.2f} MB")

        elapsed = time.perf_counter() - start_time
        logger.info(f"Totale verwerkingstijd: {elapsed:.2f} seconden")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=rotated_output.pdf"}
        )

    except Exception as e:
        logger.error(f"Interne fout: {e}")
        raise HTTPException(status_code=500, detail=f"Interne fout: {str(e)}")

    finally:
        ocr_lock.release()
