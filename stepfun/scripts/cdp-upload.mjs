const endpoint = process.argv[2] ?? "http://127.0.0.1:9223";
const files = process.argv.slice(3);
if (!files.length) throw new Error("Pass at least one absolute file path");
const pages = await (await fetch(`${endpoint}/json/list`)).json();
const page = pages.find((item) => item.type === "page" && item.url.includes("127.0.0.1"));
if (!page) throw new Error("No local application page found");
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let sequence = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  const handler = pending.get(message.id);
  if (!handler) return;
  pending.delete(message.id);
  if (message.error) handler.reject(new Error(message.error.message));
  else handler.resolve(message.result);
});
function send(method, params = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
await send("DOM.enable");
const documentResult = await send("DOM.getDocument", { depth: -1 });
const queryResult = await send("DOM.querySelector", {
  nodeId: documentResult.root.nodeId,
  selector: "input[type=file]",
});
if (!queryResult.nodeId) throw new Error("File input not found");
await send("DOM.setFileInputFiles", { nodeId: queryResult.nodeId, files });
socket.close();
console.log(`Uploaded ${files.length} files`);
