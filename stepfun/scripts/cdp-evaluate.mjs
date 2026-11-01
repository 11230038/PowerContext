const endpoint = process.argv[2] ?? "http://127.0.0.1:9222";
const expression = process.argv[3] ?? "document.body.innerText";
const pages = await (await fetch(`${endpoint}/json/list`)).json();
const page = pages.find((item) => item.type === "page" && item.url.includes("127.0.0.1"));
if (!page) throw new Error("No local application page found");
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
const result = await new Promise((resolve, reject) => {
  const timeout = setTimeout(() => reject(new Error("CDP evaluation timed out")), 5_000);
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id !== 1) return;
    clearTimeout(timeout);
    resolve(message);
  });
  socket.send(JSON.stringify({
    id: 1,
    method: "Runtime.evaluate",
    params: { expression, returnByValue: true, awaitPromise: true },
  }));
});
socket.close();
console.log(JSON.stringify(result.result?.result?.value ?? result, null, 2));
