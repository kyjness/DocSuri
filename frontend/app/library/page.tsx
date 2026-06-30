import { redirect } from 'next/navigation';

const LIBRARY_ENTRY_PATH = process.env.DOCSURI_LIBRARY_ENTRY_PATH || '/library/saved';

export default function LibraryPage() {
  redirect(LIBRARY_ENTRY_PATH);
}
