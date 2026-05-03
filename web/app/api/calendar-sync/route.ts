import { auth } from "@/auth"
import { NextRequest, NextResponse } from "next/server"

const API = process.env.BACKEND_API_URL ?? "http://localhost:8000"

export async function POST(req: NextRequest) {
  const session = await auth()
  if (!session?.user?.email) {
    return NextResponse.json({ error: "Unauthenticated" }, { status: 401 })
  }

  const { meetingId, tasks } = await req.json()
  const userId = session.user.email
  const accessToken = session.accessToken

  if (!accessToken) {
    return NextResponse.json({ error: "No Google access token" }, { status: 401 })
  }

  // Register token with backend so it can create events
  await fetch(`${API}/auth/google/token-direct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, access_token: accessToken }),
  }).catch(() => null)

  const res = await fetch(
    `${API}/meetings/${meetingId}/calendar-sync?user_id=${encodeURIComponent(userId)}`,
    { method: "POST" }
  )
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
