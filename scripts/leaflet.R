x <- rnorm(3)
y <- rnorm(length(x))
label <- c("öpiso","Ép","*ererf*")
data <- data.frame(x,y,label)
library(leaflet)
leafMap <- leaflet(data=data) %>%
  addProviderTiles("CartoDB.Positron") %>%
  addCircleMarkers(~x,~y,
                   color = "red", radius=3, stroke=FALSE,
                   fillOpacity = 0.8, opacity = 0.8,
                   popup=~label)
library(htmlwidgets)
library(htmltools)
setwd("~")
dir.create("./leaflet")
setwd("./leaflet")
saveWidget(leafMap, "leafMap.html")
