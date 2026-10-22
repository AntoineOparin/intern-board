// The company watchlist (Greenhouse, Lever and Ashby boards read directly).
import * as api from "../api";
import type { Company } from "../types";

export const companies = $state({ items: [] as Company[], loaded: false, version: 0 });

export async function loadCompanies() {
  companies.items = (await api.companies()).items;
  companies.loaded = true;
  companies.version++;
}
