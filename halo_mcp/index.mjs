// index.mjs
// npm i @openai/agents
import { Agent, run, MCPServerStdio, MCPServerStreamableHttp } from "@openai/agents";

// Brave（検索）— 同一PCで子プロセス起動（stdio）
const brave = new MCPServerStdio({
  name: "brave",
  // 公式なら: "npx -y @brave/brave-search-mcp-server"
  fullCommand: "npx -y brave-search-mcp",
  env: { BRAVE_API_KEY: process.env.BRAVE_API_KEY },
});

// Spotify（オプション）— uv が未インストールでもスキップ可能に
const spotify = new MCPServerStdio({
  name: "spotify",
  fullCommand: "node ../spotify-mcp-server/build/index.js",
});

// switchbotで電気をオンオフするMCPサーバー
const switchbot = new MCPServerStdio({
  name: "switchbot", // ← エージェント側での識別名（自由）
  fullCommand: "python ./halo_mcp/switchbot.py",
  env: {
    // 念のためバッファ無効で安定化
    PYTHONUNBUFFERED: "1",
  },
});

async function connectSafe(server, name) {
  try {
    await server.connect();
    return server;
  } catch (e) {
    console.error(`[mcp] ${name} connect skipped: ${e?.message || e}`);
    return null;
  }
}

const listServers = [];
listServers.push(await connectSafe(switchbot, "switchbot"));
listServers.push(await connectSafe(brave, "brave"));
listServers.push(await connectSafe(spotify, "spotify"));
const activeServers = listServers.filter(Boolean);

try {
  const agent = new Agent({
    name: "multi-mcp-agent",
    model: "gpt-4o-mini",
    instructions: `
あなたはMCPツールを使ってユーザーの依頼を解決します。
- Web/ニュース/画像の検索: 「brave」
- 音楽の検索/再生/キュー/プレイリスト操作: 「spotify」
- 電気の操作: 「switchbot」
- 出典URLや実行手順を簡潔に示し、日本語で答える。
- あなたはガンダムのハロです。ハロ、電気をつけた。など片言で返信する。`,
    mcpServers: activeServers,
  });

  const query =
    process.argv[2] ??
    "switchbotで電気をオン";
  const result = await run(agent, query);

  process.stdout.write(JSON.stringify({ output: result.finalOutput }) + "\n");
} catch (e) {
  console.error(e?.stack || String(e));
  process.exitCode = 1;
} finally {
  const listToClose = [];
  if (activeServers.includes(brave)) listToClose.push(brave.close());
  if (activeServers.includes(spotify)) listToClose.push(spotify.close());
  if (activeServers.includes(switchbot)) listToClose.push(switchbot.close());
  await Promise.allSettled(listToClose);
}
