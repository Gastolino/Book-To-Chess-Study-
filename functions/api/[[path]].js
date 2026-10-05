// Every request under /api/ goes to the library's server (server/app.js).
import { handle } from "../../server/app.js";

export const onRequest = (context) => handle(context.request, context.env);
