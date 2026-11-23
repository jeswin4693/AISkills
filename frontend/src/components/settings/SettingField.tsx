"use client";

import { useId } from "react";
import { Badge, Button } from "@/components/ui";
import { sourceNote } from "@/lib/settings";
import type { SettingItem } from "@/lib/types";

const INPUT = "mt-1 block w-full max-w-md rounded-md border border-border bg-bg px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60";

interface Props {
  item: SettingItem;
  /** What the field shows now (what was typed, else what is saved). A key's field starts empty: the server never sends one. */
  value: string;
  onChange: (value: string) => void;
  /** Why the server refused this setting's value, if it did (the message never repeats the value). */
  problem?: string;
  /** A key that is saved and was asked to be removed on the next save. */
  removing?: boolean;
  onToggleRemove?: () => void;
}

function Status({ item, removing }: { item: SettingItem; removing: boolean }) {
  if (removing) return <Badge tone="warn">Will be removed</Badge>;
  if (item.source === "environment") return <Badge tone="info" title="A real environment variable wins over the .env file">Set outside .env</Badge>;
  if (item.kind === "secret") return item.set ? <Badge tone="ok">Saved</Badge> : <Badge>Not set</Badge>;
  return null;
}

/** One setting, by its kind. A key is a password field that starts empty, is never filled in, and is dropped from the page once saved. */
export function SettingField({ item, value, onChange, problem, removing = false, onToggleRemove }: Props) {
  const id = useId();
  const note = sourceNote(item);
  const locked = !item.editable;
  let control: React.ReactNode;
  if (item.kind === "secret") {
    control = (
      <input
        id={id}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={locked || removing}
        placeholder={item.set ? "Saved. Paste a new key to replace it." : "Paste the key"}
        autoComplete="new-password"
        spellCheck={false}
        aria-invalid={problem ? true : undefined}
        className={`${INPUT} font-mono`}
      />
    );
  } else if (item.kind === "choice") {
    control = (
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={locked} aria-invalid={problem ? true : undefined} className={INPUT}>
        <option value="">(not set)</option>
        {item.choices.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    );
  } else if (item.kind === "flag") {
    control = (
      <label className="mt-1 flex items-center gap-2 text-sm">
        <input id={id} type="checkbox" checked={value === "1"} onChange={(e) => onChange(e.target.checked ? "1" : "")} disabled={locked} />
        On
      </label>
    );
  } else {
    control = (
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={locked}
        inputMode={item.kind === "number" ? "decimal" : undefined}
        autoComplete="off"
        spellCheck={false}
        aria-invalid={problem ? true : undefined}
        className={`${INPUT} font-mono`}
      />
    );
  }
  return (
    <div className="space-y-0.5" data-setting={item.name}>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="font-medium">
          {item.label}
        </label>
        <Status item={item} removing={removing} />
        {item.kind === "secret" && item.set && item.editable && onToggleRemove && (
          <Button variant="ghost" className="px-2 py-0.5 text-xs" onClick={onToggleRemove}>
            {removing ? "Keep it" : "Remove it"}
          </Button>
        )}
      </div>
      {control}
      <p className="text-xs text-muted">{item.help}</p>
      {note && <p className="text-xs text-warn">{note}</p>}
      {problem && (
        <p role="alert" className="text-sm text-bad">
          {problem}
        </p>
      )}
    </div>
  );
}
