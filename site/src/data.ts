import type { AtlasData, EntityDetail, GraphIndexes, GraphManifest, GraphView } from "./types";

const viewIds: GraphView["id"][] = [
  "story",
  "bottleneck",
  "optimization",
  "evidence",
  "deployment",
  "all",
];

function dataRoot(pathname: string): string {
  const study = pathname.match(/\/studies\/([^/]+)\/v(\d+)\/?/);
  const relative = study ? `data/studies/${study[1]}/v${study[2]}` : "data";
  return `${import.meta.env.BASE_URL}${relative}`;
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Unable to load ${url} (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function loadAtlas(pathname = window.location.pathname): Promise<AtlasData> {
  const root = dataRoot(pathname);
  const globalRoot = `${import.meta.env.BASE_URL}data`;
  const globalGraphRequest =
    root === globalRoot ? null : getJson<AtlasData["graph"]>(`${globalRoot}/graph.json`);
  const [manifest, graph, indexes, ...viewValues] = await Promise.all([
    getJson<GraphManifest>(`${root}/manifest.json`),
    getJson<AtlasData["graph"]>(`${root}/graph.json`),
    getJson<GraphIndexes>(`${root}/indexes.json`),
    ...viewIds.map((id) => getJson<GraphView>(`${root}/views/${id}.json`)),
  ]);
  const globalGraph = await globalGraphRequest;
  return {
    root,
    manifest,
    graph,
    referenceNodes: globalGraph?.nodes ?? graph.nodes,
    indexes,
    views: Object.fromEntries(viewValues.map((view) => [view.id, view])) as AtlasData["views"],
  };
}

export function loadEntity(atlas: AtlasData, detailPath: string): Promise<EntityDetail> {
  return getJson<EntityDetail>(`${atlas.root}/${detailPath}`);
}
