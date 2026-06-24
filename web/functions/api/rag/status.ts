interface Env {
  RAG_SERVICE_KEY?: string;
  RAG_SERVICE_URL?: string;
  RAG_DOMAIN?: string;
}

type PagesContext = {
  env: Env;
};

export function onRequestGet(context: PagesContext): Response {
  return Response.json(
    {
      configured: Boolean(context.env.RAG_SERVICE_KEY),
      service_url: context.env.RAG_SERVICE_URL ?? "default",
      domain: context.env.RAG_DOMAIN ?? "research-papers-cited1000-v2",
    },
    {
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );
}
