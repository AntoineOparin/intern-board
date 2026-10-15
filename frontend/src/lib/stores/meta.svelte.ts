import * as api from "../api";
import type { Meta } from "../types";

export const meta = $state({ data: null as Meta | null });

export async function loadMeta(): Promise<Meta> {
  const data = await api.meta();
  meta.data = data;
  return data;
}
