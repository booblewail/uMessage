"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { CalendarPlus, LoaderCircle } from "lucide-react";
import { api, toApiError, type DetectedEvent } from "@/lib/api";
import { editsFromForm, formFromEvent, formProblem, withAllDay, type EventForm } from "@/lib/eventForm";

interface Props {
  event: DetectedEvent;
  /** Called with the Detected Event once Confirmed (its Calendar Entry exists). */
  onConfirmed: (event: DetectedEvent) => void;
  onClose: () => void;
}

const INPUT =
  "w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none disabled:bg-slate-50";

/**
 * "Add to Calendar": the Detected Event's details, pre-filled and editable (times in the
 * browser's local time), then Confirm creates its Calendar Entry.
 */
export function EventEditDialog({ event, onConfirmed, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const inFlight = useRef(false); // a double-click sends one request (the API also refuses a second)
  const [form, setForm] = useState<EventForm>(() => formFromEvent(event));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problem = formProblem(form);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  const change = (fields: Partial<EventForm>) => setForm((current) => ({ ...current, ...fields }));

  const submit = async (submitted: FormEvent) => {
    submitted.preventDefault();
    if (problem || inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    setError(null);
    try {
      onConfirmed(await api.confirmEvent(event.id, editsFromForm(form)));
    } catch (failure) {
      setError(toApiError(failure).message);
      setSaving(false);
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <dialog
      ref={dialog}
      aria-labelledby={`event-edit-${event.id}`}
      data-testid="event-edit-dialog"
      onCancel={(cancelled) => {
        cancelled.preventDefault(); // Escape: close through onClose, never mid-save
        if (!saving) onClose();
      }}
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-2xl p-0 text-slate-900 shadow-xl backdrop:bg-slate-900/40"
    >
      <form onSubmit={(submitted) => void submit(submitted)} className="flex flex-col gap-3 p-5">
        <h2 id={`event-edit-${event.id}`} className="flex items-center gap-2 text-base font-semibold">
          <CalendarPlus className="size-5 text-indigo-600" aria-hidden />
          Add to Calendar
        </h2>
        <Field label="Title">
          <input
            value={form.title}
            onChange={(e) => change({ title: e.target.value })}
            disabled={saving}
            autoFocus
            data-testid="event-title-input"
            className={INPUT}
          />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.allDay}
            onChange={(e) => setForm((current) => withAllDay(current, e.target.checked))}
            disabled={saving}
            data-testid="event-all-day-input"
            className="size-4 accent-indigo-600"
          />
          All day
        </label>
        <div className="grid grid-cols-2 gap-3">
          <Field label={form.allDay ? "First day" : "Starts"}>
            <input
              type={form.allDay ? "date" : "datetime-local"}
              value={form.allDay ? form.startDate : form.startTime}
              onChange={(e) => change(form.allDay ? { startDate: e.target.value } : { startTime: e.target.value })}
              disabled={saving}
              required
              data-testid="event-start-input"
              className={INPUT}
            />
          </Field>
          <Field label={form.allDay ? "Last day" : "Ends (optional)"}>
            <input
              type={form.allDay ? "date" : "datetime-local"}
              value={form.allDay ? form.endDate : form.endTime}
              min={form.allDay ? form.startDate : form.startTime}
              onChange={(e) => change(form.allDay ? { endDate: e.target.value } : { endTime: e.target.value })}
              disabled={saving}
              data-testid="event-end-input"
              className={INPUT}
            />
          </Field>
        </div>
        <Field label="Location">
          <input
            value={form.location}
            onChange={(e) => change({ location: e.target.value })}
            disabled={saving}
            placeholder="None"
            data-testid="event-location-input"
            className={INPUT}
          />
        </Field>
        {(problem || error) && (
          <p role="alert" data-testid="event-edit-error" className="text-sm text-rose-700">
            {problem ?? `Couldn't add it to your calendar: ${error}`}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            data-testid="cancel-event-edit"
            className="rounded-full border border-slate-300 px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving || problem !== null}
            data-testid="confirm-event"
            className="inline-flex items-center gap-1.5 rounded-full bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-slate-300"
          >
            {saving && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
            {saving ? "Adding…" : "Confirm"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
      {label}
      {children}
    </label>
  );
}
