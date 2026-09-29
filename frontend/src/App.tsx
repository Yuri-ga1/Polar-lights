import { useRef, useState } from "react";
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "./api/client";
import { type Product } from "./api/contracts";
import { useWorkspace } from "./store";
import { ChartCard } from "./components/ChartCard";
import { Parameters } from "./components/Parameters";
import {
  LayoutActions,
  WorkspaceTools,
  useShortcuts,
} from "./components/WorkspaceTools";
import { intersects } from "./workspace/geometry";
import type { Rect } from "./workspace/schema";
function LibraryItem({ product }: { product: Product }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: product.productId,
    disabled: !product.available,
  });
  return (
    <button
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`library-item ${isDragging ? "dragging" : ""}`}
      disabled={!product.available}
      onClick={() => useWorkspace.getState().add(product)}
      title={product.description || `${product.title} · ${product.graphType}`}
    >
      <span className={`product-icon ${product.graphType}`}>
        {product.graphType === "map"
          ? "◎"
          : product.graphType === "keogram"
            ? "▦"
            : "⌁"}
      </span>
      <span>
        <strong>{product.title}</strong>
        <small>{product.available ? product.graphType : "Unavailable"}</small>
      </span>
      <span className="add-symbol">+</span>
    </button>
  );
}
function ProductList({ products }: { products: Product[] }) {
  const [top, setTop] = useState(0);
  if (products.length < 80)
    return products.map((p) => <LibraryItem key={p.productId} product={p} />);
  const rowHeight = 76,
    start = Math.max(0, Math.floor(top / rowHeight) - 3),
    end = Math.min(products.length, start + 14);
  return (
    <div
      className="virtual-library"
      onScroll={(e) => setTop(e.currentTarget.scrollTop)}
      style={{ height: 500, overflowY: "auto" }}
    >
      <div
        style={{ height: products.length * rowHeight, position: "relative" }}
      >
        {products.slice(start, end).map((p, i) => (
          <div
            key={p.productId}
            style={{
              position: "absolute",
              top: (start + i) * rowHeight,
              height: rowHeight,
              width: "100%",
            }}
          >
            <LibraryItem product={p} />
          </div>
        ))}
      </div>
    </div>
  );
}
function Canvas({ products }: { products: Product[] }) {
  const charts = useWorkspace((s) => s.charts);
  const origin = useRef<{ x: number; y: number; additive: boolean } | null>(
    null,
  );
  const [rubber, setRubber] = useState<Rect | null>(null);
  const { setNodeRef, isOver } = useDroppable({ id: "canvas" });
  const width = Math.max(
    1400,
    ...charts.map((c) => c.layoutSpec.x + c.layoutSpec.width + 100),
  );
  const height = Math.max(
    1000,
    ...charts.map((c) => c.layoutSpec.y + c.layoutSpec.height + 100),
  );
  return (
    <div className="canvas-scroll">
      <div
        ref={setNodeRef}
        id="workspace-canvas"
        data-testid="canvas"
        className={`canvas ${isOver ? "drop-active" : ""}`}
        style={{ width, height }}
        onPointerDown={(e) => {
          if (e.target !== e.currentTarget) return;
          const box = e.currentTarget.getBoundingClientRect();
          origin.current = {
            x: e.clientX - box.left,
            y: e.clientY - box.top,
            additive: e.shiftKey,
          };
          e.currentTarget.setPointerCapture(e.pointerId);
          if (!e.shiftKey) useWorkspace.getState().select(null);
        }}
        onPointerMove={(e) => {
          if (!origin.current) return;
          const box = e.currentTarget.getBoundingClientRect(),
            x = e.clientX - box.left,
            y = e.clientY - box.top;
          setRubber({
            x: Math.min(x, origin.current.x),
            y: Math.min(y, origin.current.y),
            width: Math.abs(x - origin.current.x),
            height: Math.abs(y - origin.current.y),
          });
        }}
        onPointerUp={() => {
          if (origin.current && rubber)
            useWorkspace.getState().selectMany(
              charts
                .filter((c) => intersects(c.layoutSpec, rubber))
                .map((c) => c.id),
              origin.current.additive,
            );
          origin.current = null;
          setRubber(null);
        }}
        onPointerCancel={() => {
          origin.current = null;
          setRubber(null);
        }}
      >
        {!charts.length && (
          <div className="empty-canvas">
            <span className="eyebrow">YOUR SCIENTIFIC WORKSPACE</span>
            <h1>
              A clearer view of
              <br />
              space weather.
            </h1>
            <p>
              Drag a product here, or click one in the library.
              <br />
              Choose its parameters and build your first chart.
            </p>
            <span className="empty-target">＋</span>
          </div>
        )}
        {charts.map((chart) => (
          <ChartCard
            key={chart.id}
            chart={chart}
            product={products.find((p) => p.productId === chart.productId)}
          />
        ))}
        {rubber && (
          <div
            data-export-ignore
            className="selection-rectangle"
            style={{
              left: rubber.x,
              top: rubber.y,
              width: rubber.width,
              height: rubber.height,
            }}
          />
        )}
      </div>
    </div>
  );
}
export default function App() {
  useShortcuts();
  const catalog = useQuery({
    queryKey: ["catalog"],
    queryFn: ({ signal }) => apiClient.catalog(signal),
  });
  const charts = useWorkspace((s) => s.charts);
  const selectedId = useWorkspace((s) => s.selectedId);
  const selectedIds = useWorkspace((s) => s.selectedIds);
  const [leftOpen, setLeftOpen] = useState(true),
    [rightOpen, setRightOpen] = useState(true);
  const persistenceError = useWorkspace((s) => s.persistenceError);
  const [search, setSearch] = useState("");
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 7 } }),
  );
  const products = catalog.data?.products ?? [];
  const selected = charts.find((c) => c.id === selectedId);
  const selectedProduct = products.find(
    (p) => p.productId === selected?.productId,
  );
  const groups = [...new Set(products.map((p) => p.graphType))];
  function drop(event: DragEndEvent) {
    if (event.over?.id !== "canvas") return;
    const product = products.find((p) => p.productId === event.active.id);
    const canvas = document
      .getElementById("workspace-canvas")
      ?.getBoundingClientRect();
    const rect = event.active.rect.current.translated;
    if (product?.available && canvas && rect)
      useWorkspace.getState().add(product, {
        x: Math.max(0, Math.min(canvas.width - 560, rect.left - canvas.left)),
        y: Math.max(0, Math.min(canvas.height - 380, rect.top - canvas.top)),
      });
  }
  return (
    <DndContext sensors={sensors} onDragEnd={drop}>
      <div className="app-shell">
        <header className="app-header">
          <button
            aria-label="Toggle library"
            aria-expanded={leftOpen}
            onClick={() => setLeftOpen(!leftOpen)}
          >
            Library
          </button>
          <div className="brand-mark">◒</div>
          <div>
            <strong>Polar Lights</strong>
            <small>Scientific workspace</small>
          </div>
          <div className="header-divider" />
          <span className="workspace-name">Untitled workspace</span>
          <span className="header-status">
            {import.meta.env.VITE_MOCK_API === "true"
              ? "Demo · synthetic data"
              : "Backend API"}{" "}
            <i /> {charts.length} charts
          </span>
          <button
            aria-label="Toggle inspector"
            aria-expanded={rightOpen}
            onClick={() => setRightOpen(!rightOpen)}
          >
            Inspector
          </button>
        </header>
        {persistenceError && (
          <div className="storage-alert" role="alert">
            {persistenceError}
          </div>
        )}
        <main
          className={`${leftOpen ? "" : "left-collapsed"} ${rightOpen ? "" : "right-collapsed"}`}
        >
          <aside className="library" hidden={!leftOpen}>
            <div className="panel-heading">
              <span className="eyebrow">EXPLORE</span>
              <h2>Chart library</h2>
              <p>Click to add · drag to place</p>
            </div>
            <input
              className="search"
              aria-label="Search products"
              placeholder="Search products…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {catalog.isPending && <p role="status">Loading catalog…</p>}
            {catalog.error && (
              <div role="alert">
                <p>Cannot load catalog: {catalog.error.message}</p>
                <button onClick={() => void catalog.refetch()}>
                  Retry catalog
                </button>
              </div>
            )}
            {groups.map((group) => (
              <details key={group} open className="library-group">
                <summary>
                  {
                    {
                      map: "Maps",
                      timeseries: "Time series",
                      keogram: "Two-dimensional",
                    }[group]
                  }
                </summary>
                <ProductList
                  products={products.filter(
                    (p) =>
                      p.graphType === group &&
                      p.title.toLowerCase().includes(search.toLowerCase()),
                  )}
                />
              </details>
            ))}
            <div className="library-note">
              Catalog supplied by the backend.
              <br />
              All times are UTC.
            </div>
          </aside>
          <section className="workspace">
            <WorkspaceTools />
            <div className="canvas-toolbar">
              <strong>Workspace</strong>
              <span>{selectedIds.length} selected</span>
              <small>Drag headers to move · pull corners to resize</small>
            </div>
            <Canvas products={products} />
          </section>
          <aside className="inspector" hidden={!rightOpen}>
            {selectedIds.length > 1 ? (
              <div className="parameters">
                <h2>{selectedIds.length} charts selected</h2>
                <p>Common layout actions</p>
                <LayoutActions />
              </div>
            ) : selected && selectedProduct ? (
              <Parameters
                key={selected.id}
                chart={selected}
                product={selectedProduct}
              />
            ) : (
              <div className="inspector-empty">
                <span className="eyebrow">INSPECTOR</span>
                <h2>Make it yours</h2>
                <p>Select a chart to configure its data and appearance.</p>
              </div>
            )}
          </aside>
        </main>
      </div>
    </DndContext>
  );
}
