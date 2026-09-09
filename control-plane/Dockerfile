FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY main.go topology.go ./
RUN CGO_ENABLED=0 go build -o /control-plane .

FROM alpine:3.20
WORKDIR /app
COPY --from=build /control-plane /app/control-plane
EXPOSE 8080
ENTRYPOINT ["/app/control-plane"]
