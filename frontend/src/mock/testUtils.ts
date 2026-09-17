/** vitest jsdom 下 localStorage 可能被 Node 原生实现遮蔽，测试里用内存 polyfill */
export function ensureLocalStorage(): Storage {
  const g = globalThis as unknown as { localStorage?: Storage }
  if (g.localStorage && typeof g.localStorage.getItem === 'function') {
    return g.localStorage
  }
  const map = new Map<string, string>()
  const storage: Storage = {
    get length() {
      return map.size
    },
    clear: () => {
      map.clear()
    },
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    removeItem: (key: string) => {
      map.delete(key)
    },
    setItem: (key: string, value: string) => {
      map.set(key, String(value))
    },
  }
  g.localStorage = storage
  return storage
}
