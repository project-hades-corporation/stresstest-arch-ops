import WordExtractor from "word-extractor";

export const runtime = "nodejs";

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const MAX_TEXT_LENGTH = 40_000;

export async function POST(request: Request): Promise<Response> {
  const formData = await request.formData();
  const file = formData.get("file");
  if (!(file instanceof File)) {
    return Response.json({ error: "Choose a Word document to import." }, { status: 400 });
  }
  if (file.size > MAX_FILE_SIZE) {
    return Response.json({ error: "Files must be 10 MB or smaller." }, { status: 413 });
  }

  let text: string;
  try {
    const document = await new WordExtractor().extract(
      Buffer.from(await file.arrayBuffer())
    );
    text = document.getBody().trim();
  } catch {
    return Response.json(
      { error: "Could not read this .doc file. Verify it is a valid Word document and try again." },
      { status: 422 }
    );
  }

  if (!text) {
    return Response.json({ error: "No readable text was found in that file." }, { status: 422 });
  }
  if (text.length > MAX_TEXT_LENGTH) {
    return Response.json(
      { error: "Extracted text exceeds 40,000 characters. Upload a smaller document." },
      { status: 413 }
    );
  }

  return Response.json({ text });
}
