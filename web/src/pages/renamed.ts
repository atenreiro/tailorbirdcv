// An analysis can rename an application (it learns the company): the new address keeps the page that was
// open, with its unsaved work. Any other application gets a fresh page (WorkspacePage), so an AI step that
// finishes after you moved on can never write into the application you're looking at now.
const sameApp = new Map<string, string>()

/** The identity of the application page for this address (unchanged by a rename). */
export const pageKey = (id: string) => sameApp.get(id) ?? id

/** Record that the application at `from` is now at `to`. */
export function renamed(from: string, to: string) {
  if (from !== to) sameApp.set(to, pageKey(from))
}
