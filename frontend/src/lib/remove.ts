/** Words and rules for the two things that cannot be undone: deleting a library entry, and erasing a person's data (docs/data-removal.md).
 * The typed confirmation here only helps the person: the server checks it again and refuses a request that lacks it. */

import { plural } from "./format";
import type { DeleteReport, EraseReport } from "./types";

/** The name typed exactly (spaces around it ignored). Never true for an empty name, so an empty box cannot confirm anything. */
export const typedName = (typed: string, name: string): boolean => name.trim() !== "" && typed.trim() === name.trim();

/** The address typed, whatever its case (spaces around it ignored). Never true for an empty address. */
export const typedEmail = (typed: string, email: string): boolean => email.trim() !== "" && typed.trim().toLowerCase() === email.trim().toLowerCase();

/** The lines the delete dialog shows. `kindLabel` is the kind's own noun ("skill", "agent", "MCP server"). */
export function deleteWords(kindLabel: string, versions: number): string[] {
  return [
    `This deletes the ${kindLabel} and its ${plural(versions, "version")} from your library.`,
    "It also deletes the backups that were made when you installed over an existing copy.",
    "This cannot be undone.",
    "Plugins you already built keep their own copies. Folders you installed it into are not touched.",
  ];
}

/** "Deleted commit-writer: 2 versions and 1 backup." and, when the disk would not give everything up, a plain sentence saying so. */
export function deletedNotice(r: DeleteReport, name: string): string {
  const parts = [plural(r.versions, "version"), ...(r.backups > 0 ? [plural(r.backups, "backup")] : [])];
  const counted = parts.join(" and ");
  const left = r.leftover ? " Some files could not be removed from the disk (a program may be holding them); they are no longer part of your library." : "";
  return `Deleted ${name}: ${counted}.${left}`;
}

/** What the erase dialog says is removed and what is kept, and why the usage record is kept. */
export function eraseWords(): { removes: string[]; keeps: string[] } {
  return {
    removes: [
      "Their library of every kind (skills, agents, plugins, MCP servers) and its backups",
      "Their builds and the files in them",
      "Their suggestion runs and Testing Lab runs",
      "Their saved model key",
    ],
    keeps: [
      "The account itself. It stays turned off, so they cannot sign in until you turn it back on, and then they start empty.",
      "The record of how many model calls they made (counts only). Their daily allowance is counted from it, so erasing it would let them start again with a fresh one.",
    ],
  };
}

/** "Erased: 3 builds, 1 suggestion run, 2 test runs, and their saved model key. Their files are gone." */
export function erasedNotice(r: EraseReport): string {
  const counted = [plural(r.builds, "build"), plural(r.suggestion_runs, "suggestion run"), plural(r.lab_runs, "test run")].join(", ");
  const key = r.key_removed ? ", and their saved model key" : "";
  const files = r.files_left
    ? " Some files could not be removed from the disk (a program may be holding them); they no longer belong to anything, so try again later."
    : " Their files are gone.";
  return `Erased: ${counted}${key}.${files}`;
}
