// Grounding citations like "[ref:app/api/seed/route.ts::module]" are valuable
// to the generation/evaluation pipeline but are noise for readers. Strip them
// at display time so the stored document and citation checks stay intact.

const CITATION = /[ \t]*\[ref:[^\]]+\][ \t]*/g;
const TRAILING_PARTIAL_CITATION = /[ \t]*\[ref:[^\]]*$/;
const LEADING_PUNCTUATION = /^[.,;:!?)\]]/;
const WORD_CHAR = /[\w`]/;

function replaceCitation(match: string, offset: number, whole: string): string {
  const before = whole[offset - 1] ?? "";
  const after = whole[offset + match.length] ?? "";
  const onOwnLine =
    (offset === 0 || before === "\n" || before === "\r") &&
    (after === "" || after === "\n" || after === "\r");

  if (onOwnLine) return "";
  // "Postgres [ref:x]." -> "Postgres." rather than "Postgres ."
  if (LEADING_PUNCTUATION.test(after)) return "";
  // "a[ref:x]b" -> "a b" rather than "ab"
  if (WORD_CHAR.test(before) && WORD_CHAR.test(after)) return " ";
  return "";
}

export function stripCitations(text: string): string {
  return text.replace(CITATION, replaceCitation).replace(/[ \t]+$/gm, "");
}

// While tokens stream in, a citation can be cut in half. Hide the incomplete
// tail too so partial markers never flash on screen.
export function stripCitationsForStream(text: string): string {
  return stripCitations(text.replace(TRAILING_PARTIAL_CITATION, ""));
}
