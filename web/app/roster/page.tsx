"use client"

import { useSession, signIn } from "next-auth/react"
import { useEffect, useState } from "react"
import Link from "next/link"
import {
  Plus, Trash2, Pencil, Check, X, Loader2, Users, ArrowLeft, ChevronDown, ChevronUp,
} from "lucide-react"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

interface Worker {
  worker_id: string
  name: string
  aliases: string[]
  role: string | null
  email: string | null
  skills: string[]
}

const EMPTY_FORM: Omit<Worker, "worker_id"> = {
  name: "", aliases: [], role: "", email: "", skills: [],
}

function TagList({
  values, onChange, placeholder,
}: { values: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  const [input, setInput] = useState("")
  const add = () => {
    const v = input.trim()
    if (v && !values.includes(v)) onChange([...values, v])
    setInput("")
  }
  return (
    <div className="flex flex-wrap gap-1.5 items-center">
      {values.map(v => (
        <span key={v} className="flex items-center gap-1 bg-sky-50 border border-sky-200 text-sky-700 text-xs px-2 py-0.5 rounded-full">
          {v}
          <button onClick={() => onChange(values.filter(x => x !== v))} className="text-slate-400 hover:text-red-500">
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add() } }}
        onBlur={add}
        placeholder={placeholder}
        className="bg-transparent text-xs text-slate-900 placeholder-slate-400 focus:outline-none w-28"
      />
    </div>
  )
}

function WorkerForm({
  initial, onSave, onCancel, saving,
}: {
  initial: Omit<Worker, "worker_id">
  onSave: (w: Omit<Worker, "worker_id">) => void
  onCancel: () => void
  saving: boolean
}) {
  const [form, setForm] = useState(initial)
  const set = (k: keyof typeof form, v: unknown) => setForm(f => ({ ...f, [k]: v }))

  return (
    <div className="space-y-3 p-4 bg-white rounded-xl border border-slate-200 shadow-sm shadow-sky-900/5">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-slate-500 mb-1 block">Name *</label>
          <input value={form.name} onChange={e => set("name", e.target.value)}
            placeholder="Full name"
            className="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-sky-500" />
        </div>
        <div>
          <label className="text-xs text-slate-500 mb-1 block">Role</label>
          <input value={form.role ?? ""} onChange={e => set("role", e.target.value || null)}
            placeholder="e.g. Engineer"
            className="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-sky-500" />
        </div>
      </div>
      <div>
        <label className="text-xs text-slate-500 mb-1 block">Email</label>
        <input value={form.email ?? ""} onChange={e => set("email", e.target.value || null)}
          placeholder="email@company.com"
          className="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-sky-500" />
      </div>
      <div>
        <label className="text-xs text-slate-500 mb-1 block">Aliases <span className="text-slate-600">(press Enter to add)</span></label>
        <div className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 min-h-[38px]">
          <TagList values={form.aliases} onChange={v => set("aliases", v)} placeholder="Add alias..." />
        </div>
      </div>
      <div>
        <label className="text-xs text-slate-500 mb-1 block">Skills <span className="text-slate-600">(press Enter to add)</span></label>
        <div className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 min-h-[38px]">
          <TagList values={form.skills} onChange={v => set("skills", v)} placeholder="Add skill..." />
        </div>
      </div>
      <div className="flex gap-2 pt-1">
        <button onClick={() => onSave(form)} disabled={!form.name.trim() || saving}
          className="flex items-center gap-1.5 px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 rounded-lg text-sm font-medium text-white transition-colors">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          Save
        </button>
        <button onClick={onCancel}
          className="flex items-center gap-1.5 px-4 py-2 border border-slate-200 hover:border-sky-300 rounded-lg text-sm text-slate-700 hover:text-slate-900 transition-colors bg-white">
          <X size={14} /> Cancel
        </button>
      </div>
    </div>
  )
}

function WorkerRow({ worker, onEdit, onDelete }: {
  worker: Worker
  onEdit: () => void
  onDelete: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const hasExtra = (worker.aliases.length > 0) || (worker.skills.length > 0)

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm shadow-sky-900/5">
      <div className="flex items-center gap-3 px-4 py-3">
        <div className="w-9 h-9 rounded-full bg-sky-50 border border-sky-200 flex items-center justify-center flex-shrink-0">
          <span className="text-sm font-semibold text-sky-700">{worker.name[0]?.toUpperCase()}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-900">{worker.name}</span>
            {worker.role && (
              <span className="text-xs text-slate-600 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-full">{worker.role}</span>
            )}
          </div>
          {worker.email && (
            <span className="text-xs text-slate-500">{worker.email}</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {hasExtra && (
            <button onClick={() => setExpanded(e => !e)}
              className="p-1.5 text-slate-400 hover:text-slate-900 transition-colors">
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          )}
          <button onClick={onEdit}
            className="p-1.5 text-slate-400 hover:text-sky-600 transition-colors">
            <Pencil size={14} />
          </button>
          <button onClick={onDelete}
            className="p-1.5 text-slate-400 hover:text-red-500 transition-colors">
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {expanded && hasExtra && (
        <div className="px-4 pb-3 space-y-2 border-t border-slate-200 pt-2 bg-slate-50/60">
          {worker.aliases.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-slate-500">Aliases:</span>
              {worker.aliases.map(a => (
                <span key={a} className="text-xs bg-slate-100 text-slate-700 border border-slate-200 px-2 py-0.5 rounded-full">{a}</span>
              ))}
            </div>
          )}
          {worker.skills.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-slate-500">Skills:</span>
              {worker.skills.map(s => (
                <span key={s} className="text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full">{s}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function RosterPage() {
  const { data: session, status } = useSession()
  const [workers, setWorkers] = useState<Worker[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const r = await fetch(`${API}/workers`)
      const data = await r.json()
      setWorkers(data.workers ?? [])
    } catch {
      setError("Failed to load roster")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { if (status === "authenticated") load() }, [status])

  const handleAdd = async (form: Omit<Worker, "worker_id">) => {
    setSaving(true)
    try {
      const r = await fetch(`${API}/workers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      })
      if (!r.ok) {
        const d = await r.json()
        setError(d.detail ?? "Failed to add worker")
      } else {
        setAdding(false)
        await load()
      }
    } finally {
      setSaving(false)
    }
  }

  const handleEdit = async (worker_id: string, form: Omit<Worker, "worker_id">) => {
    setSaving(true)
    try {
      const r = await fetch(`${API}/workers/${worker_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, worker_id }),
      })
      if (!r.ok) {
        const d = await r.json()
        setError(d.detail ?? "Failed to update worker")
      } else {
        setEditingId(null)
        await load()
      }
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (worker_id: string) => {
    setDeletingId(worker_id)
    try {
      await fetch(`${API}/workers/${worker_id}`, { method: "DELETE" })
      await load()
    } finally {
      setDeletingId(null)
    }
  }

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 size={28} className="animate-spin text-sky-500" />
      </div>
    )
  }

  if (status === "unauthenticated") {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <p className="text-slate-600">Sign in to manage the roster.</p>
        <button onClick={() => signIn("google")}
          className="px-5 py-2.5 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-sm font-medium transition-colors">
          Sign in with Google
        </button>
      </div>
    )
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <div className="max-w-2xl mx-auto px-4 py-10 space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="p-2 text-slate-500 hover:text-slate-900 transition-colors rounded-lg hover:bg-white border border-transparent hover:border-slate-200">
              <ArrowLeft size={18} />
            </Link>
            <div>
              <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
                <Users size={20} className="text-sky-600" />
                Worker Roster
              </h1>
              <p className="text-xs text-slate-500 mt-0.5">
                {session?.user?.email} · {workers.length} member{workers.length !== 1 ? "s" : ""}
              </p>
            </div>
          </div>
          {!adding && (
            <button onClick={() => { setAdding(true); setEditingId(null) }}
              className="flex items-center gap-1.5 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-sm font-medium transition-colors">
              <Plus size={15} /> Add worker
            </button>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="flex items-center justify-between bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            {error}
            <button onClick={() => setError(null)}><X size={14} /></button>
          </div>
        )}

        {/* Add form */}
        {adding && (
          <WorkerForm
            initial={EMPTY_FORM}
            onSave={handleAdd}
            onCancel={() => setAdding(false)}
            saving={saving}
          />
        )}

        {/* Worker list */}
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={22} className="animate-spin text-sky-500" />
          </div>
        ) : workers.length === 0 && !adding ? (
          <div className="text-center py-16 text-slate-500 bg-white border border-slate-200 rounded-2xl">
            <Users size={36} className="mx-auto mb-3 opacity-30 text-sky-500" />
            <p className="text-sm">No workers yet. Add one to get started.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {workers.map(w => (
              editingId === w.worker_id ? (
                <WorkerForm
                  key={w.worker_id}
                  initial={{ name: w.name, aliases: w.aliases, role: w.role, email: w.email, skills: w.skills }}
                  onSave={form => handleEdit(w.worker_id, form)}
                  onCancel={() => setEditingId(null)}
                  saving={saving}
                />
              ) : (
                <div key={w.worker_id} className={deletingId === w.worker_id ? "opacity-40 pointer-events-none" : ""}>
                  <WorkerRow
                    worker={w}
                    onEdit={() => { setEditingId(w.worker_id); setAdding(false) }}
                    onDelete={() => handleDelete(w.worker_id)}
                  />
                </div>
              )
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
