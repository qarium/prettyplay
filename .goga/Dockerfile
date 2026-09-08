FROM qarium/goga-python-3.14:1.3

USER root

COPY agents/architector.sh /home/goga/bin/architector-as-claude.sh
COPY agents/developer.sh /home/goga/bin/developer-as-claude.sh
COPY agents/reviewer.sh /home/goga/bin/reviewer-as-claude.sh
COPY agents/product.sh /home/goga/bin/product-as-claude.sh
COPY agents/manager.sh /home/goga/bin/manager-as-claude.sh
COPY agents/analyst.sh /home/goga/bin/analyst-as-claude.sh
COPY agents/tester.sh /home/goga/bin/tester-as-claude.sh

RUN chmod +x /home/goga/bin/*.sh

USER goga