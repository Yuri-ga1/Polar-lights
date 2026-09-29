import { useState } from "react";
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
      title={
        product.description ||
        `${product.graphType} · ${product.availabilityStrategy}`
      }
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
function Canvas({ products }: { products: Product[] }) {
  const charts = useWorkspace((s) => s.charts);
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
          if (e.target === e.currentTarget)
            useWorkspace.getState().select(null);
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
      </div>
    </div>
  );
}
export default function App() {
  const catalog = useQuery({
    queryKey: ["catalog"],
    queryFn: ({ signal }) => apiClient.catalog(signal),
  });
  const charts = useWorkspace((s) => s.charts);
  const selectedId = useWorkspace((s) => s.selectedId);
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
        </header>
        {persistenceError && (
          <div className="storage-alert" role="alert">
            {persistenceError}
          </div>
        )}
        <main>
          <aside className="library">
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
                {products
                  .filter(
                    (p) =>
                      p.graphType === group &&
                      p.title.toLowerCase().includes(search.toLowerCase()),
                  )
                  .map((p) => (
                    <LibraryItem key={p.productId} product={p} />
                  ))}
              </details>
            ))}
            <div className="library-note">
              Catalog supplied by the backend.
              <br />
              All times are UTC.
            </div>
          </aside>
          <section className="workspace">
            <div className="canvas-toolbar">
              <strong>Workspace</strong>
              <span>Free canvas</span>
              <small>Drag headers to move · pull corners to resize</small>
            </div>
            <Canvas products={products} />
          </section>
          <aside className="inspector">
            {selected && selectedProduct ? (
              <Parameters chart={selected} product={selectedProduct} />
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
