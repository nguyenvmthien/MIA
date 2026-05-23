import { auth } from "@/auth"
import { NextRequest, NextResponse } from "next/server"

const API = process.env.BACKEND_API_URL ?? "http://localhost:8000"

function backendHeaders(userId: string) {
  const token = process.env.BACKEND_USER_TOKEN ?? process.env.BACKEND_ADMIN_TOKEN
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-User-Id": userId,
  }
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

export async function POST(req: NextRequest) {
  const session = await auth()
  if (!session?.user?.email) {
    return NextResponse.json({ error: "Unauthenticated" }, { status: 401 })
  }

  const { meetingId, taskIds } = await req.json()
  const userId = session.user.email
  const accessToken = session.accessToken

  if (session.error === "RefreshTokenError") {
    return NextResponse.json({ error: "Google token expired — please sign in again" }, { status: 401 })
  }
  if (!accessToken) {
    return NextResponse.json({ error: "No Google access token" }, { status: 401 })
  }

  // Register token with backend so it can create events
  await fetch(`${API}/auth/google/token-direct`, {
    method: "POST",
    headers: backendHeaders(userId),
    body: JSON.stringify({ user_id: userId, access_token: accessToken }),
  }).catch(() => null)

  const res = await fetch(
    `${API}/meetings/${meetingId}/calendar-sync?user_id=${encodeURIComponent(userId)}`,
    {
      method: "POST",
      headers: backendHeaders(userId),
      body: JSON.stringify({ task_ids: taskIds ?? null }),
    }
  )
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
