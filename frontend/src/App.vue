<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">B</span>
        <div>
          <h1>burph5</h1>
          <p>本地请求重放与调试台</p>
        </div>
      </div>
      <nav class="nav-links">
        <RouterLink to="/" active-class="is-active">历史记录</RouterLink>
        <RouterLink to="/proxy" active-class="is-active">代理记录</RouterLink>
        <RouterLink to="/repeater" active-class="is-active">请求重放</RouterLink>
        <RouterLink to="/collections" active-class="is-active">请求集合</RouterLink>
        <RouterLink to="/settings" active-class="is-active">系统设置</RouterLink>
      </nav>
    </aside>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>
