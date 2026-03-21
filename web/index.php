<?php
$data = json_decode(file_get_contents(__DIR__ . '/data.json'), true) ?? [];
$q    = trim($_GET['q'] ?? '');

if ($q !== '') {
    $data = array_filter($data, fn($r) =>
        str_contains($r['code'], $q) || mb_strpos($r['name'], $q) !== false
    );
}
?>
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>日証金 申込停止銘柄一覧</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: sans-serif; font-size: 15px; background: #f5f5f5; color: #222; }
  header { background: #1a1a2e; color: #fff; padding: 16px 20px; }
  header h1 { font-size: 18px; font-weight: bold; }
  .search-bar { padding: 16px 20px; background: #fff; border-bottom: 1px solid #ddd; }
  .search-bar form { display: flex; gap: 8px; max-width: 480px; }
  .search-bar input { flex: 1; padding: 8px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 15px; }
  .search-bar button { padding: 8px 18px; background: #1a1a2e; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
  .count { padding: 10px 20px; font-size: 13px; color: #666; }
  table { width: 100%; border-collapse: collapse; background: #fff; }
  th { background: #eee; padding: 10px 16px; text-align: left; font-size: 13px; border-bottom: 2px solid #ccc; }
  td { padding: 10px 16px; border-bottom: 1px solid #eee; vertical-align: middle; }
  tr:hover td { background: #f9f9f9; }
  .code { font-weight: bold; color: #1a1a2e; white-space: nowrap; }
  .date { white-space: nowrap; color: #555; }
  a { color: #1a6abf; text-decoration: none; }
  a:hover { text-decoration: underline; }
  @media (max-width: 600px) {
    td, th { padding: 8px 10px; font-size: 13px; }
  }
</style>
</head>
<body>
<header>
  <h1>日証金 申込停止銘柄一覧</h1>
</header>
<div class="search-bar">
  <form method="get">
    <input type="text" name="q" placeholder="銘柄コードまたは銘柄名で検索" value="<?= htmlspecialchars($q) ?>">
    <button type="submit">検索</button>
    <?php if ($q): ?><a href="?" style="padding:8px 12px;color:#666;font-size:13px;">クリア</a><?php endif; ?>
  </form>
</div>
<div class="count">
  <?= count($data) ?>件
  <?= $q ? '（検索: ' . htmlspecialchars($q) . '）' : '' ?>
</div>
<table>
  <thead>
    <tr>
      <th>申込停止日</th>
      <th>コード</th>
      <th>銘柄名</th>
      <th>社発番号</th>
      <th>PDF</th>
    </tr>
  </thead>
  <tbody>
    <?php foreach ($data as $r): ?>
    <tr>
      <td class="date"><?= htmlspecialchars($r['teishi_date']) ?></td>
      <td class="code"><?= htmlspecialchars($r['code']) ?></td>
      <td><?= htmlspecialchars($r['name']) ?></td>
      <td style="font-size:13px;color:#888;"><?= htmlspecialchars($r['shahatsu'] ?? '') ?></td>
      <td><a href="<?= htmlspecialchars($r['pdf_url']) ?>" target="_blank">PDF</a></td>
    </tr>
    <?php endforeach; ?>
  </tbody>
</table>
</body>
</html>
