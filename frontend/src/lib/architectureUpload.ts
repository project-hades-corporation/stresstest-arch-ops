const MAX_FILE_SIZE = 10 * 1024 * 1024;
const MAX_TEXT_LENGTH = 40_000;
const MAX_PDF_PAGES = 30;

export async function extractArchitectureFile(
  file: File,
  onProgress: (message: string) => void
): Promise<string> {
  if (file.size > MAX_FILE_SIZE) {
    throw new Error("Files must be 10 MB or smaller.");
  }

  const extension = file.name.split(".").pop()?.toLowerCase();
  let text: string;

  if (["md", "markdown", "txt"].includes(extension ?? "")) {
    text = await file.text();
  } else if (extension === "doc") {
    onProgress("Reading Word document...");
    const formData = new FormData();
    formData.set("file", file);
    const response = await fetch("/api/extract-word", {
      method: "POST",
      body: formData,
    });
    const result = (await response.json()) as { text?: string; error?: string };
    if (!response.ok) {
      throw new Error(result.error || `Could not read Word document (${response.status}).`);
    }
    if (typeof result.text !== "string") {
      throw new Error("The Word document parser returned no text.");
    }
    text = result.text;
  } else if (extension === "docx") {
    onProgress("Reading Word document...");
    const mammoth = await import("mammoth");
    const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() });
    text = result.value;
  } else if (extension === "pdf") {
    text = await extractPdf(file, onProgress);
  } else if (["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"].includes(extension ?? "")) {
    onProgress("Recognizing text in image...");
    const tesseract = await import("tesseract.js");
    const result = await tesseract.recognize(file, "eng");
    text = result.data.text;
  } else {
    throw new Error("Choose a PNG, JPG, WEBP, BMP, TIFF, PDF, DOCX, Markdown, or TXT file.");
  }

  const normalizedText = text.trim();
  if (!normalizedText) {
    throw new Error("No readable text was found in that file.");
  }
  if (normalizedText.length > MAX_TEXT_LENGTH) {
    throw new Error("Extracted text exceeds 40,000 characters. Upload a smaller document.");
  }

  return normalizedText;
}

async function extractPdf(file: File, onProgress: (message: string) => void): Promise<string> {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.mjs`;
  const document = await pdfjs.getDocument({
    data: new Uint8Array(await file.arrayBuffer()),
  }).promise;

  if (document.numPages > MAX_PDF_PAGES) {
    await document.destroy();
    throw new Error(`PDFs must have ${MAX_PDF_PAGES} pages or fewer.`);
  }

  const pages: string[] = [];
  let ocrWorker: Awaited<ReturnType<typeof import("tesseract.js").createWorker>> | undefined;

  try {
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      onProgress(`Reading PDF page ${pageNumber} of ${document.numPages}...`);
      const page = await document.getPage(pageNumber);
      const content = await page.getTextContent();
      let pageText = content.items
        .flatMap((item) => ("str" in item ? [item.str] : []))
        .join(" ")
        .trim();

      if (!pageText) {
        onProgress(`Recognizing text on scanned PDF page ${pageNumber}...`);
        ocrWorker ??= await (await import("tesseract.js")).createWorker("eng");
        const viewport = page.getViewport({ scale: 1.5 });
        const canvas = window.document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const context = canvas.getContext("2d");
        if (!context) {
          throw new Error("Could not prepare a PDF page for text recognition.");
        }
        await page.render({ canvasContext: context, viewport }).promise;
        pageText = (await ocrWorker.recognize(canvas)).data.text.trim();
        canvas.width = 0;
        canvas.height = 0;
      }

      if (pageText) pages.push(pageText);
    }
  } finally {
    await ocrWorker?.terminate();
    await document.destroy();
  }

  return pages.join("\n\n");
}
