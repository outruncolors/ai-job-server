/* HTML-escape helper. Escapes &, <, >, ", ' so output is safe in both
   text content and attribute values. */
function _escHtml(s) {
  return String(s)
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;')
    .replace(/'/g,  '&#39;');
}
