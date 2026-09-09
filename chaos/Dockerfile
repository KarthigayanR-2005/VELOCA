FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -o /chaos .

FROM alpine:3.20
WORKDIR /app
COPY --from=build /chaos /app/chaos
ENTRYPOINT ["/app/chaos"]
