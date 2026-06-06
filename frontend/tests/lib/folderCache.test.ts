import type { InfiniteData, QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";
import type { FileBrowserPage } from "@/hooks/useFileBrowser";
import { makeTestQueryClient } from "@tests/utils";
import type { NodeListItem } from "@/types/nodes";
import {
  insertNodeIntoFolderCache,
  optimisticallyPatchNode,
  optimisticallyRemoveNodes,
  patchNodeInFolderCache,
  removeNodesFromFolderCache,
} from "@/lib/folderCache";

type FolderCache = InfiniteData<FileBrowserPage>;

const KEY = ["nodes", "root"];

function node(id: string, extra: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id,
    owner_id: "owner",
    parent_id: null,
    name: `name-${id}`,
    node_type: "file",
    visibility: "private",
    path: `/${id}`,
    depth: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    is_deleted: false,
    ...extra,
  };
}

function page(items: NodeListItem[], total = items.length): FileBrowserPage {
  return { items, total, folder: null, breadcrumbs: [] };
}

function makeCache(pages: FileBrowserPage[]): FolderCache {
  return { pages, pageParams: pages.map((_, i) => i) };
}

let qc: QueryClient;

beforeEach(() => {
  qc = makeTestQueryClient();
});

describe("insertNodeIntoFolderCache", () => {
  it("ничего не делает, если кэш пуст (undefined)", () => {
    insertNodeIntoFolderCache(qc, KEY, node("x"));
    expect(qc.getQueryData(KEY)).toBeUndefined();
  });

  it("ничего не делает для non-infinite кэша (нет pages)", () => {
    qc.setQueryData(KEY, { foo: "bar" });
    insertNodeIntoFolderCache(qc, KEY, node("x"));
    expect(qc.getQueryData(KEY)).toEqual({ foo: "bar" });
  });

  it("ничего не делает, если pages пустой массив", () => {
    const cache = makeCache([]);
    qc.setQueryData(KEY, cache);
    insertNodeIntoFolderCache(qc, KEY, node("x"));
    expect(qc.getQueryData(KEY)).toBe(cache);
  });

  it("добавляет node в последнюю страницу и увеличивает total", () => {
    qc.setQueryData(KEY, makeCache([page([node("a")]), page([node("b")])]));
    insertNodeIntoFolderCache(qc, KEY, node("c"));
    const result = qc.getQueryData<FolderCache>(KEY)!;
    expect(result.pages[0].items.map((i) => i.id)).toEqual(["a"]);
    expect(result.pages[1].items.map((i) => i.id)).toEqual(["b", "c"]);
    expect(result.pages[1].total).toBe(2);
  });

  it("не добавляет дубликат, если node уже есть в любой странице", () => {
    const cache = makeCache([page([node("a")]), page([node("b")])]);
    qc.setQueryData(KEY, cache);
    insertNodeIntoFolderCache(qc, KEY, node("a"));
    expect(qc.getQueryData(KEY)).toBe(cache);
  });
});

describe("removeNodesFromFolderCache", () => {
  it("раньше выходит, если множество ids пустое", () => {
    const cache = makeCache([page([node("a")])]);
    qc.setQueryData(KEY, cache);
    removeNodesFromFolderCache(qc, KEY, []);
    expect(qc.getQueryData(KEY)).toBe(cache);
  });

  it("ничего не делает, если кэш undefined", () => {
    removeNodesFromFolderCache(qc, KEY, ["a"]);
    expect(qc.getQueryData(KEY)).toBeUndefined();
  });

  it("ничего не делает для non-infinite кэша", () => {
    qc.setQueryData(KEY, { foo: 1 });
    removeNodesFromFolderCache(qc, KEY, ["a"]);
    expect(qc.getQueryData(KEY)).toEqual({ foo: 1 });
  });

  it("удаляет nodes из всех страниц и уменьшает total", () => {
    qc.setQueryData(
      KEY,
      makeCache([page([node("a"), node("b")], 2), page([node("c")], 1)]),
    );
    removeNodesFromFolderCache(qc, KEY, ["a", "c"]);
    const result = qc.getQueryData<FolderCache>(KEY)!;
    expect(result.pages[0].items.map((i) => i.id)).toEqual(["b"]);
    expect(result.pages[0].total).toBe(1);
    expect(result.pages[1].items).toEqual([]);
    expect(result.pages[1].total).toBe(0);
  });

  it("не уменьшает total ниже нуля", () => {
    qc.setQueryData(KEY, makeCache([page([node("a")], 0)]));
    removeNodesFromFolderCache(qc, KEY, ["a"]);
    const result = qc.getQueryData<FolderCache>(KEY)!;
    expect(result.pages[0].total).toBe(0);
  });

  it("оставляет страницу нетронутой, если ничего не удалено", () => {
    const pageRef = page([node("a")]);
    qc.setQueryData(KEY, makeCache([pageRef]));
    removeNodesFromFolderCache(qc, KEY, ["zzz"]);
    const result = qc.getQueryData<FolderCache>(KEY)!;
    expect(result.pages[0]).toBe(pageRef);
  });
});

describe("patchNodeInFolderCache", () => {
  it("ничего не делает, если кэш undefined", () => {
    patchNodeInFolderCache(qc, KEY, "a", { name: "new" });
    expect(qc.getQueryData(KEY)).toBeUndefined();
  });

  it("ничего не делает для non-infinite кэша", () => {
    qc.setQueryData(KEY, { foo: 1 });
    patchNodeInFolderCache(qc, KEY, "a", { name: "new" });
    expect(qc.getQueryData(KEY)).toEqual({ foo: 1 });
  });

  it("поверхностно обновляет совпадающий node во всех страницах", () => {
    qc.setQueryData(
      KEY,
      makeCache([page([node("a"), node("b")]), page([node("c")])]),
    );
    patchNodeInFolderCache(qc, KEY, "b", { name: "renamed" });
    const result = qc.getQueryData<FolderCache>(KEY)!;
    expect(result.pages[0].items[1].name).toBe("renamed");
    expect(result.pages[0].items[0].name).toBe("name-a");
    expect(result.pages[1].items[0].name).toBe("name-c");
  });

  it("оставляет кэш без изменений значений, если node отсутствует", () => {
    qc.setQueryData(KEY, makeCache([page([node("a")])]));
    patchNodeInFolderCache(qc, KEY, "missing", { name: "x" });
    const result = qc.getQueryData<FolderCache>(KEY)!;
    expect(result.pages[0].items[0].name).toBe("name-a");
  });
});

describe("optimisticallyRemoveNodes", () => {
  it("удаляет nodes и rollback восстанавливает снимок", () => {
    const cache = makeCache([page([node("a"), node("b")], 2)]);
    qc.setQueryData(KEY, cache);
    const rollback = optimisticallyRemoveNodes(qc, KEY, ["a"]);

    let result = qc.getQueryData<FolderCache>(KEY)!;
    expect(result.pages[0].items.map((i) => i.id)).toEqual(["b"]);
    expect(result.pages[0].total).toBe(1);

    rollback();
    result = qc.getQueryData<FolderCache>(KEY)!;
    expect(result.pages[0].items.map((i) => i.id)).toEqual(["a", "b"]);
    expect(result.pages[0].total).toBe(2);
  });

  it("снимок undefined, если кэша не было; rollback не падает", () => {
    const rollback = optimisticallyRemoveNodes(qc, KEY, ["a"]);
    // Кэша не было — снимок undefined; setQueryData(undefined) — no-op в react-query.
    expect(() => rollback()).not.toThrow();
    expect(qc.getQueryData(KEY)).toBeUndefined();
  });
});

describe("optimisticallyPatchNode", () => {
  it("патчит node и rollback восстанавливает снимок", () => {
    qc.setQueryData(KEY, makeCache([page([node("a", { name: "old" })])]));
    const rollback = optimisticallyPatchNode(qc, KEY, "a", { name: "new" });

    expect(qc.getQueryData<FolderCache>(KEY)!.pages[0].items[0].name).toBe("new");

    rollback();
    expect(qc.getQueryData<FolderCache>(KEY)!.pages[0].items[0].name).toBe("old");
  });
});
