FROM cubejs/cube:latest

WORKDIR /cube/conf

COPY package.json ./
RUN npm install --production

COPY . .

# Set environment defaults
ENV NODE_ENV=production
ENV CUBEJS_DB_TYPE=duckdb
ENV CUBEJS_PORT=4000
ENV CUBEJS_DEV_MODE=false

# US-8.3: the Postgres wire protocol (SQL API) port. The variable Cube reads is
# CUBEJS_PG_SQL_PORT. This image previously set CUBEJS_SQL_PORT, which is not a Cube variable --
# it binds nothing, so the SQL API was never listening on any runtime built from this image and
# every Metabase and Power BI connection was refused at the TCP layer. cube.js now refuses to
# start on that configuration; see assertSqlApiIsCoherent().
ENV CUBEJS_PG_SQL_PORT=5432

# 4000 is the REST/GraphQL API. 5432 is the SQL API.
#
# Cloud Run serves 4000 only: it routes a single container port and speaks HTTP/1, HTTP/2, gRPC
# and WebSockets, so the raw-TCP Postgres wire protocol cannot reach a Cloud Run service at any
# port. One image, two runtimes -- cube/deploy_cube_rest_cloudrun.sh for the REST half that the
# thin web app calls, cube/deploy_cube_sql_vm.sh for the TCP half that Metabase and Power BI
# connect to. docs/METABASE_CUBE_SQL.md covers the split.
EXPOSE 4000 5432

CMD ["npm", "run", "start"]
