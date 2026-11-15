import type { DataDriver } from "./contract";
import { httpDriver } from "./http";
import { localDriver } from "./local";

export const DATA_MODE = (process.env.NEXT_PUBLIC_DATA_MODE === "local" ? "local" : "api") as "api" | "local";
export const api: DataDriver = DATA_MODE === "local" ? localDriver : httpDriver;
export type { DataDriver };
