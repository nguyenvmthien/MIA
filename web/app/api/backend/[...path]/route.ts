import { auth } from "@/auth"
import { NextRequest, NextResponse } from "next/server"

const API = process.env.BACKEND_API_URL ?? "http://localhost:8000"

type Context = {
  params: Promise<{ path: string[] }>
}

function backendHeaders(userId: string, req: NextRequest) {
  const token = process.env.BACKEND_USER_TOKEN ?? process.env.BACKEND_ADMIN_TOKEN
  const headers: Record<string, string> = {
    "X-User-Id": userId,
  }
  const contentType = req.headers.get("content-type")
  if (contentType) headers["Content-Type"] = contentType
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

async function proxy(req: NextRequest, context: Context) {
  const session = await auth()
  if (!session?.user?.email) {
    return NextResponse.json({ error: "Unauthenticated" }, { status: 401 })
  }

  const { path } = await context.params
  const url = new URL(req.url)
  const upstream = new URL(path.join("/"), API.endsWith("/") ? API : `${API}/`)
  upstream.search = url.search

  const method = req.method
  const body = method === "GET" || method === "HEAD" ? undefined : await req.arrayBuffer()
  const response = await fetch(upstream, {
    method,
    headers: backendHeaders(session.user.email, req),
    body,
  })

  const responseBody = await response.arrayBuffer()
  return new NextResponse(responseBody, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/json",
    },
  })
}

export async function GET(req: NextRequest, context: Context) {
  return proxy(req, context)
}

export async function POST(req: NextRequest, context: Context) {
  return proxy(req, context)
}

export async function PUT(req: NextRequest, context: Context) {
  return proxy(req, context)
}

export async function DELETE(req: NextRequest, context: Context) {
  return proxy(req, context)
}
