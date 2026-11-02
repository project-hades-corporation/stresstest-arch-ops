export const runtime = "nodejs";

const BACKEND_URL =
  (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
const MAX_FILE_SIZE = 10 * 1024 * 1024;

export async function POST(request: Request): Promise<Response> {
  const formData = await request.formData();
  const file = formData.get("file");
  const modelOverride = formData.get("model_override");

  if (!(file instanceof File)) {
    return Response.json({ error: "No image file provided." }, { status: 400 });
  }
  if (file.size > MAX_FILE_SIZE) {
    return Response.json({ error: "Image must be 10 MB or smaller." }, { status: 413 });
  }

  const backendForm = new FormData();
  backendForm.set("file", file);
  if (typeof modelOverride === "string" && modelOverride) {
    backendForm.set("model_override", modelOverride);
  }

  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}/parse-diagram`, {
      method: "POST",
      body: backendForm,
    });
  } catch (err) {
    return Response.json(
      { error: `Could not reach the backend: ${String(err)}` },
      { status: 503 }
    );
  }

  const data: unknown = await response.json();
  return Response.json(data, { status: response.status });
}

export async function GET(): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}/models`);
  } catch (err) {
    return Response.json(
      { error: `Could not reach the backend: ${String(err)}` },
      { status: 503 }
    );
  }
  const data: unknown = await response.json();
  return Response.json(data, { status: response.status });
}
